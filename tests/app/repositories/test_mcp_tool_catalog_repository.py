"""Tests for MCPToolCatalogRepository.get_tools_for_model_config."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.repositories.mcp_server_repository import MCPServerRepository
from app.repositories.mcp_tool_catalog_repository import MCPToolCatalogRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.mcp_server import MCPServerCreate
from app.schemas.mcp_tool import MCPCatalogTool


def _make_server(db: Session, *, enabled: bool = True, server_id: str | None = None):
    sid = server_id or f"test-{uuid4().hex[:10]}"
    return MCPServerRepository(db).create_mcp_server(
        MCPServerCreate(
            server_id=sid,
            name="Test MCP",
            url="https://example.com/mcp",
            enabled=enabled,
        )
    )


def _make_config(db: Session):
    slug = f"tool-test-{uuid4().hex[:8]}"
    return ModelConfigRepository(db).create(
        {
            "slug": slug,
            "name": "Tool Test Config",
            "provider": "openai",
            "model": "gpt-4o",
        }
    )


def _fake_tool(server_id: str) -> MCPCatalogTool:
    return MCPCatalogTool(
        qualified_name=f"{server_id}__do_thing",
        original_name="do_thing",
        description="Does a thing",
        input_schema={"type": "object", "properties": {}},
        server_id=server_id,
    )


@pytest.mark.asyncio
async def test_returns_tools_from_attached_servers(db: Session):
    config = _make_config(db)
    server = _make_server(db)
    config.mcp_servers.append(server)
    db.commit()

    fake_tool = _fake_tool(server.server_id)

    with patch(
        "app.services.mcp.catalog.ToolCatalog.get_tools",
        new_callable=AsyncMock,
        return_value=[fake_tool],
    ):
        tools = await MCPToolCatalogRepository(db).get_tools_for_model_config(config.id)

    assert len(tools) == 1
    assert tools[0].qualified_name == fake_tool.qualified_name


@pytest.mark.asyncio
async def test_excludes_tools_from_disabled_servers(db: Session):
    config = _make_config(db)
    server = _make_server(db, enabled=False)
    config.mcp_servers.append(server)
    db.commit()

    with patch(
        "app.services.mcp.catalog.ToolCatalog.get_tools",
        new_callable=AsyncMock,
        return_value=[_fake_tool(server.server_id)],
    ) as mock_get:
        tools = await MCPToolCatalogRepository(db).get_tools_for_model_config(config.id)

    assert tools == []
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_excludes_tools_from_soft_deleted_servers(db: Session):
    config = _make_config(db)
    server = _make_server(db)
    config.mcp_servers.append(server)
    db.commit()

    MCPServerRepository(db).delete_mcp_server(server.id)

    with patch(
        "app.services.mcp.catalog.ToolCatalog.get_tools",
        new_callable=AsyncMock,
        return_value=[_fake_tool(server.server_id)],
    ) as mock_get:
        tools = await MCPToolCatalogRepository(db).get_tools_for_model_config(config.id)

    assert tools == []
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_skips_failing_server_and_returns_remaining(db: Session):
    config = _make_config(db)
    server_a = _make_server(db, server_id=f"srv-a-{uuid4().hex[:6]}")
    server_b = _make_server(db, server_id=f"srv-b-{uuid4().hex[:6]}")
    config.mcp_servers.extend([server_a, server_b])
    db.commit()

    fake_tool_b = _fake_tool(server_b.server_id)

    async def _get_tools_side_effect(server, headers, **kwargs):
        if server.server_id == server_a.server_id:
            raise RuntimeError("connection refused")
        return [fake_tool_b]

    with patch(
        "app.services.mcp.catalog.ToolCatalog.get_tools",
        new_callable=AsyncMock,
        side_effect=_get_tools_side_effect,
    ):
        tools = await MCPToolCatalogRepository(db).get_tools_for_model_config(config.id)

    assert len(tools) == 1
    assert tools[0].server_id == server_b.server_id


@pytest.mark.asyncio
async def test_no_attached_servers_returns_empty(db: Session):
    config = _make_config(db)

    with patch(
        "app.services.mcp.catalog.ToolCatalog.get_tools",
        new_callable=AsyncMock,
    ) as mock_get:
        tools = await MCPToolCatalogRepository(db).get_tools_for_model_config(config.id)

    assert tools == []
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_only_returns_tools_from_attached_not_all_servers(db: Session):
    config = _make_config(db)
    attached = _make_server(db, server_id=f"attached-{uuid4().hex[:6]}")
    _make_server(db, server_id=f"unattached-{uuid4().hex[:6]}")
    config.mcp_servers.append(attached)
    db.commit()

    fake_tool = _fake_tool(attached.server_id)

    with patch(
        "app.services.mcp.catalog.ToolCatalog.get_tools",
        new_callable=AsyncMock,
        return_value=[fake_tool],
    ):
        tools = await MCPToolCatalogRepository(db).get_tools_for_model_config(config.id)

    assert len(tools) == 1
    assert tools[0].server_id == attached.server_id
