"""Orchestrates loading tools across enabled MCP servers for a request context."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional, cast
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionFactory
from app.infra.logging_config import get_logger
from app.models.mcp_server import MCPServer
from app.models.model_config import model_config_mcp_servers
from app.services.mcp.catalog import ToolCatalog
from app.schemas.mcp_tool import MCPCatalogTool
from app.services.credential_applier import CredentialApplier
from app.repositories.mcp_server_repository import MCPServerRepository

logger = get_logger(__name__)

# An MCP server (detached, columns loaded) and the auth headers to call it with.
ServerConnection = tuple[MCPServer, dict[str, str]]


class MCPToolCatalogRepository:
    """
    Loads tools from all enabled MCP servers for a given request.

    Uses MCPServerRepository.get_enabled_servers(), CredentialRepository for auth headers,
    and ToolCatalog for cached tool fetching per server.

    The servers and their headers load in one short session in the threadpool;
    the tool fetches that follow hold no database connection (linden-api
    SDD 0012).
    """

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def get_tools_for_request(
        self,
        *,
        user_id: Optional[UUID] = None,
    ) -> list[MCPCatalogTool]:
        """
        Return tools from all enabled MCP servers.

        Resolves auth headers per server (credential-driven) and fetches tools
        via ToolCatalog (cached). Per-server failures are logged and skipped.
        """
        connections = await run_in_threadpool(self._enabled_server_connections, user_id)
        return await _fetch_tools(connections)

    async def get_tools_for_model_config(
        self,
        model_config_id: UUID,
        *,
        user_id: Optional[UUID] = None,
    ) -> list[MCPCatalogTool]:
        """
        Return tools from MCP servers attached to the given ModelConfig.

        Only includes servers that are enabled and not soft-deleted.
        Per-server failures are logged and skipped.
        """
        connections = await run_in_threadpool(
            self._model_config_server_connections, model_config_id, user_id
        )
        return await _fetch_tools(connections)

    def _enabled_server_connections(
        self, user_id: Optional[UUID]
    ) -> list[ServerConnection]:
        with self._sessions() as db:
            servers = MCPServerRepository(db).get_enabled_servers()
            return _resolve_connections(db, servers, user_id)

    def _model_config_server_connections(
        self, model_config_id: UUID, user_id: Optional[UUID]
    ) -> list[ServerConnection]:
        stmt = (
            select(MCPServer)
            .join(
                model_config_mcp_servers,
                MCPServer.id == model_config_mcp_servers.c.mcp_server_id,
            )
            .where(
                model_config_mcp_servers.c.model_config_id == model_config_id,
                MCPServer.enabled.is_(True),
                MCPServer.deleted_at.is_(None),
            )
            .order_by(MCPServer.server_id)
        )
        with self._sessions() as db:
            servers = db.execute(stmt).scalars().all()
            return _resolve_connections(db, servers, user_id)


def _resolve_connections(
    db: Session, servers: Sequence[MCPServer], user_id: Optional[UUID]
) -> list[ServerConnection]:
    """Pair each server with its auth headers and detach it from ``db``.

    Detached before the session commits, so the columns ToolCatalog reads stay
    loaded once it closes. A server whose credentials fail is logged and
    skipped.
    """
    cred_repo = CredentialApplier(db)
    connections: list[ServerConnection] = []
    for server in servers:
        try:
            headers = cred_repo.apply_for_user(
                cast(Optional[UUID], server.credential_id),
                user_id=user_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to load tools for MCP server %s: %s",
                server.server_id,
                e,
                exc_info=True,
            )
            continue
        connections.append((server, headers))
    for server in servers:
        db.expunge(server)
    return connections


async def _fetch_tools(connections: list[ServerConnection]) -> list[MCPCatalogTool]:
    catalog = ToolCatalog.new()
    all_tools: list[MCPCatalogTool] = []
    for server, headers in connections:
        try:
            all_tools.extend(await catalog.get_tools(server, headers))
        except Exception as e:
            logger.warning(
                "Failed to load tools for MCP server %s: %s",
                server.server_id,
                e,
                exc_info=True,
            )
    return all_tools
