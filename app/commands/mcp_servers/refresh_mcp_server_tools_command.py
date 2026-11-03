"""Command to force-refresh the tool catalog for an MCP server."""

from __future__ import annotations

from typing import cast

from app.services.mcp.catalog import ToolCatalog
from app.models.mcp_server import MCPServer
from app.schemas.mcp_server import MCPToolsRefreshResponse


class RefreshMcpServerToolsCommand:
    """
    Command to force-refresh tools from an MCP server.
    The caller resolves the server and its auth headers (in a short session);
    this command only talks to the MCP server, holding no DB connection.
    """

    async def execute(
        self,
        mcp_server: MCPServer,
        headers: dict[str, str],
    ) -> MCPToolsRefreshResponse:
        """
        Force-refresh tools from the MCP server and return the response.

        Args:
            mcp_server: The MCP server to refresh tools for (detached).
            headers: Auth headers resolved for the calling user.

        Returns:
            MCPToolsRefreshResponse with server_id and tools_count.

        Raises:
            Exception: When tools cannot be fetched from the MCP server.
        """
        catalog = ToolCatalog.new()
        tools = await catalog.get_tools(mcp_server, headers, force_refresh=True)
        return MCPToolsRefreshResponse(
            server_id=cast(str, mcp_server.server_id),
            tools_count=len(tools),
        )
