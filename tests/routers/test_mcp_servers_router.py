"""Router tests for /mcp-servers."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.mcp_server_repository import MCPServerRepository
from app.schemas.mcp_server import MCPServerCreate, MCPToolsRefreshResponse


def _create_payload(**overrides):
    sid = f"mcp-rt-{uuid4().hex[:10]}"
    base = {
        "server_id": sid,
        "name": "Router MCP",
        "url": "https://example.com/mcp",
        "credential_id": None,
        "tool_prefix": "example",
        "tool_cache_ttl_seconds": 300,
        "enabled": True,
        "extended_info": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def existing_mcp_server(db: Session):
    repo = MCPServerRepository(db)
    return repo.create_mcp_server(
        MCPServerCreate.model_validate(_create_payload()),
    )


def test_create_mcp_server(client: TestClient):
    payload = _create_payload()
    r = client.post("/mcp-servers", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["server_id"] == payload["server_id"]
    assert data["name"] == payload["name"]
    assert data["url"] == payload["url"]
    assert "id" in data


def test_create_mcp_server_invalid_url_returns_422(client: TestClient):
    payload = _create_payload()
    payload["url"] = "not-a-url"
    r = client.post("/mcp-servers", json=payload)
    assert r.status_code == 422


def test_list_mcp_servers(client: TestClient, existing_mcp_server):
    r = client.get("/mcp-servers")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    ids = {item["server_id"] for item in data["items"]}
    assert existing_mcp_server.server_id in ids


def test_get_mcp_server(client: TestClient, existing_mcp_server):
    r = client.get(f"/mcp-servers/{existing_mcp_server.id}")
    assert r.status_code == 200
    assert r.json()["id"] == str(existing_mcp_server.id)


def test_get_mcp_server_not_found(client: TestClient):
    r = client.get(f"/mcp-servers/{uuid4()}")
    assert r.status_code == 404
    assert r.json()["detail"] == "MCP server not found"


def test_update_mcp_server(client: TestClient, existing_mcp_server):
    r = client.patch(
        f"/mcp-servers/{existing_mcp_server.id}",
        json={"name": "Renamed MCP"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed MCP"


def test_delete_mcp_server(client: TestClient, existing_mcp_server):
    sid = existing_mcp_server.id
    r = client.delete(f"/mcp-servers/{sid}")
    assert r.status_code == 204

    r2 = client.get(f"/mcp-servers/{sid}")
    assert r2.status_code == 404


def test_refresh_mcp_server_tools(client: TestClient, existing_mcp_server):
    with patch(
        "app.routers.mcp_servers_router.RefreshMcpServerToolsCommand.execute",
        new_callable=AsyncMock,
        return_value=MCPToolsRefreshResponse(
            server_id=existing_mcp_server.server_id,
            tools_count=2,
        ),
    ):
        r = client.post(f"/mcp-servers/{existing_mcp_server.id}/refresh-tools")
    assert r.status_code == 200
    body = r.json()
    assert body["server_id"] == existing_mcp_server.server_id
    assert body["tools_count"] == 2
