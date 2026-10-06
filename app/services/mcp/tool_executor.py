"""Executes MCP tool calls with timeout and structured error mapping."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from tessera_sdk.mcp import MCPEvent, MCPMetadataError, parse_mcp_metadata

from app.infra.logging_config import get_logger
from app.services.mcp.client_factory import client_context
from app.services.credential_applier import CredentialApplier
from app.repositories.mcp_server_repository import MCPServerRepository

logger = get_logger(__name__)


def _to_llm_output(value: Any) -> str | dict[str, Any]:
    """Convert tool result to JSON-serializable format for LLM."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, int, float, bool)):
        return {"result": value}
    try:
        serialized = json.loads(json.dumps(value, default=str))
        return serialized if isinstance(serialized, dict) else {"result": serialized}
    except (TypeError, ValueError):
        return {"result": str(value)}


@dataclass(frozen=True)
class MCPToolCallResult:
    """Outcome of one MCP tool call.

    ``agent_value`` is derived only from the normal MCP result and is what the
    model sees; metadata never replaces or alters it. ``events`` holds the
    validated Tessera domain events from the result's ``_meta``, when requested.
    """

    agent_value: str | dict[str, Any]
    events: tuple[MCPEvent, ...] = field(default_factory=tuple)


class MCPToolExecutor:
    """
    Executes call_tool(original_name, args) against an MCP server.

    Enforces timeout, resolves auth via CredentialRepository, and maps errors
    to structured responses for the LLM.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    async def execute(
        self,
        *,
        server_id: str,
        original_name: str,
        args: dict[str, Any],
        user_id: Optional[UUID] = None,
        timeout_seconds: float = 20.0,
    ) -> str | dict[str, Any]:
        """Execute a tool and return only the value for the LLM."""
        result = await self.execute_with_metadata(
            server_id=server_id,
            original_name=original_name,
            args=args,
            user_id=user_id,
            timeout_seconds=timeout_seconds,
        )
        return result.agent_value

    async def execute_with_metadata(
        self,
        *,
        server_id: str,
        original_name: str,
        args: dict[str, Any],
        user_id: Optional[UUID] = None,
        timeout_seconds: float = 20.0,
        parse_metadata: bool = False,
    ) -> MCPToolCallResult:
        """
        Execute a tool on the given MCP server.

        Args:
            server_id: MCP server identifier from registry.
            original_name: Tool name as exposed by the MCP server.
            args: Tool arguments (JSON-serializable dict).
            user_id: Optional user ID for delegated auth.
            timeout_seconds: Max execution time.
            parse_metadata: Parse Tessera events from the result's ``_meta``.
                Off by default so callers that did not opt in pay no cost.

        Returns:
            The LLM-facing value (or error dict on failure) and, when
            requested, validated domain events from a successful result.
        """
        mcp_svc = MCPServerRepository(self._db)
        cred_svc = CredentialApplier(self._db)

        server = mcp_svc.get_mcp_server_by_server_id(server_id)
        if server is None:
            return MCPToolCallResult(
                {
                    "error": "Tool execution failed",
                    "reason": f"Server {server_id!r} not found",
                }
            )

        headers = cred_svc.apply_for_user(
            server.credential_id,
            user_id=user_id,
        )

        try:
            async with client_context(server.url, headers) as client:
                result = await asyncio.wait_for(
                    client.call_tool(
                        original_name, arguments=args or {}, raise_on_error=False
                    ),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "MCP tool %s timed out after %ss", original_name, timeout_seconds
            )
            return MCPToolCallResult(
                {
                    "error": "Tool execution failed",
                    "reason": "Request timed out",
                }
            )
        except Exception as e:
            logger.warning("MCP tool %s failed: %s", original_name, e, exc_info=True)
            return MCPToolCallResult(
                {
                    "error": "Tool execution failed",
                    "reason": str(e),
                }
            )

        if result.is_error:
            reason = (
                str(getattr(result, "data", result)) if result.data else "Unknown error"
            )
            # Failed tools never contribute domain events.
            return MCPToolCallResult(
                {"error": "Tool execution failed", "reason": reason}
            )

        events = (
            _parse_events(result.meta, server_id, original_name)
            if parse_metadata
            else ()
        )
        return MCPToolCallResult(_to_llm_output(result.data), events)


def _parse_events(
    meta: Any, server_id: str, original_name: str
) -> tuple[MCPEvent, ...]:
    """Validate Tessera events in MCP ``_meta``; drop them all if invalid.

    Invalid metadata never fails the tool call. Only the stable error code is
    logged, never the rejected values.
    """
    if not meta:
        return ()
    try:
        return tuple(parse_mcp_metadata(meta).events)
    except MCPMetadataError as e:
        logger.warning(
            "Ignored invalid MCP metadata from tool %s on server %s: %s",
            original_name,
            server_id,
            e.code,
        )
        return ()
