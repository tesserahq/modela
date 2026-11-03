"""MCP servers API: CRUD for the MCP Server Registry."""

from typing import Optional, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies
from app.commands.mcp_servers import (
    CreateMcpServerCommand,
    DeleteMcpServerCommand,
    RefreshMcpServerToolsCommand,
    UpdateMcpServerCommand,
)
from app.db import DbSession, SessionFactory, ShortSessions
from app.models.mcp_server import MCPServer
from app.routers.utils.dependencies import get_mcp_server_by_id
from app.schemas.mcp_server import (
    MCPServerCreate,
    MCPServerRead,
    MCPServerUpdate,
    MCPToolsListResponse,
    MCPToolsRefreshResponse,
)
from app.repositories.mcp_server_repository import MCPServerRepository
from app.services.credential_applier import CredentialApplier
from app.services.mcp.catalog import ToolCatalog
from tessera_sdk.server.dependencies.auth import get_current_user  # type: ignore[import-untyped]

router = APIRouter(
    prefix="/mcp-servers",
    tags=["mcp-servers"],
    responses={404: {"description": "Not found"}},
)


async def infer_domain(request: Request) -> Optional[str]:
    return "*"


RESOURCE_MCP_SERVERS = "mcp_server"
rbac = build_rbac_dependencies(
    resource=RESOURCE_MCP_SERVERS,
    domain_resolver=infer_domain,
)


@router.get("", response_model=Page[MCPServerRead])
def list_mcp_servers(
    db: DbSession,
    params: Params = Depends(),
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
) -> Page[MCPServerRead]:
    """List all MCP servers with pagination."""
    svc = MCPServerRepository(db)
    query = svc.get_mcp_servers_query()
    return paginate(query, params=params)


@router.post("", response_model=MCPServerRead, status_code=201)
def create_mcp_server(
    data: MCPServerCreate,
    db: DbSession,
    _authorized: bool = Depends(rbac["create"]),
    _current_user=Depends(get_current_user),
) -> MCPServerRead:
    """Create a new MCP server."""
    command = CreateMcpServerCommand(db)
    return command.execute(
        data,
        created_by_id=getattr(_current_user, "id", None),
    )


@router.get("/{id}", response_model=MCPServerRead)
def get_mcp_server(
    mcp_server: MCPServer = Depends(get_mcp_server_by_id),
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
) -> MCPServerRead:
    """Get an MCP server by ID."""
    return mcp_server


@router.patch("/{id}", response_model=MCPServerRead)
def update_mcp_server(
    data: MCPServerUpdate,
    db: DbSession,
    mcp_server: MCPServer = Depends(get_mcp_server_by_id),
    _authorized: bool = Depends(rbac["update"]),
    _current_user=Depends(get_current_user),
) -> MCPServerRead:
    """Update an MCP server."""
    command = UpdateMcpServerCommand(db)
    updated = command.execute(
        cast(UUID, mcp_server.id),
        data,
        updated_by_id=getattr(_current_user, "id", None),
    )

    return updated


@router.get(
    "/{id}/tools",
    response_model=MCPToolsListResponse,
)
async def list_mcp_server_tools(
    id: UUID,
    sessions: ShortSessions,
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
) -> MCPToolsListResponse:
    """List the tool catalog for this MCP server (cached, unless expired)."""
    mcp_server, headers = await run_in_threadpool(
        _load_server_connection, sessions, id, getattr(_current_user, "id", None)
    )
    catalog = ToolCatalog.new()
    tools = await catalog.get_tools(mcp_server, headers)
    return MCPToolsListResponse(
        server_id=cast(str, mcp_server.server_id),
        tools=tools,
    )


@router.post(
    "/{id}/refresh-tools",
    response_model=MCPToolsRefreshResponse,
)
async def refresh_mcp_server_tools(
    id: UUID,
    sessions: ShortSessions,
    _authorized: bool = Depends(rbac["update"]),
    _current_user=Depends(get_current_user),
) -> MCPToolsRefreshResponse:
    """Force-refresh the tool catalog for this MCP server."""
    mcp_server, headers = await run_in_threadpool(
        _load_server_connection, sessions, id, getattr(_current_user, "id", None)
    )
    return await RefreshMcpServerToolsCommand().execute(mcp_server, headers)


def _load_server_connection(
    sessions: SessionFactory, id: UUID, user_id: Optional[UUID]
) -> tuple[MCPServer, dict[str, str]]:
    """Look up the server and its auth headers in a short session, so the
    MCP call that follows holds no DB connection. The server comes back
    detached with its columns loaded."""
    with sessions() as db:
        mcp_server = MCPServerRepository(db).get_mcp_server(id)
        if mcp_server is None:
            raise HTTPException(status_code=404, detail="MCP server not found")
        headers = CredentialApplier(db).apply_for_user(
            cast(Optional[UUID], mcp_server.credential_id),
            user_id=user_id,
        )
        db.expunge(mcp_server)
    return mcp_server, headers


@router.delete("/{id}", status_code=204)
def delete_mcp_server(
    db: DbSession,
    mcp_server: MCPServer = Depends(get_mcp_server_by_id),
    _authorized: bool = Depends(rbac["delete"]),
    _current_user=Depends(get_current_user),
) -> None:
    """Soft delete an MCP server."""
    command = DeleteMcpServerCommand(db)
    command.execute(
        cast(UUID, mcp_server.id),
        deleted_by_id=getattr(_current_user, "id", None),
    )
