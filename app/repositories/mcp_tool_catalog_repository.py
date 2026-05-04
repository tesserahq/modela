"""Orchestrates loading tools across enabled MCP servers for a request context."""

from __future__ import annotations

from typing import Optional, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.logging_config import get_logger
from app.models.mcp_server import MCPServer
from app.models.model_config import model_config_mcp_servers
from app.services.mcp.catalog import ToolCatalog
from app.schemas.mcp_tool import MCPCatalogTool
from app.services.credential_applier import CredentialApplier
from app.repositories.mcp_server_repository import MCPServerRepository

logger = get_logger(__name__)


class MCPToolCatalogRepository:
    """
    Loads tools from all enabled MCP servers for a given request.

    Uses MCPServerRepository.get_enabled_servers(), CredentialRepository for auth headers,
    and ToolCatalog for cached tool fetching per server.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

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
        mcp_repo = MCPServerRepository(self._db)
        cred_repo = CredentialApplier(self._db)
        catalog = ToolCatalog.new()

        servers = mcp_repo.get_enabled_servers()
        all_tools: list[MCPCatalogTool] = []

        for server in servers:
            try:
                headers = cred_repo.apply_for_user(
                    cast(Optional[UUID], server.credential_id),
                    user_id=user_id,
                )
                tools = await catalog.get_tools(server, headers)
                all_tools.extend(tools)
            except Exception as e:
                logger.warning(
                    "Failed to load tools for MCP server %s: %s",
                    server.server_id,
                    e,
                    exc_info=True,
                )
                continue

        return all_tools

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
        servers = self._db.execute(stmt).scalars().all()

        cred_repo = CredentialApplier(self._db)
        catalog = ToolCatalog.new()
        all_tools: list[MCPCatalogTool] = []

        for server in servers:
            try:
                headers = cred_repo.apply_for_user(
                    cast(Optional[UUID], server.credential_id),
                    user_id=user_id,
                )
                tools = await catalog.get_tools(server, headers)
                all_tools.extend(tools)
            except Exception as e:
                logger.warning(
                    "Failed to load tools for MCP server %s: %s",
                    server.server_id,
                    e,
                    exc_info=True,
                )

        return all_tools
