"""Router tests for ModelConfig ↔ MCPServer association endpoints."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.mcp_server_repository import MCPServerRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.mcp_server import MCPServerCreate


def _mcp_server_payload(**overrides):
    sid = f"rt-{uuid4().hex[:10]}"
    base = {
        "server_id": sid,
        "name": "Router Test MCP",
        "url": "https://example.com/mcp",
        "credential_id": None,
        "tool_prefix": None,
        "tool_cache_ttl_seconds": 300,
        "enabled": True,
        "extended_info": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def existing_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": f"assoc-test-{uuid4().hex[:8]}",
            "name": "Association Test Config",
            "provider": "openai",
            "model": "gpt-4o",
        }
    )


@pytest.fixture
def existing_server(db: Session):
    return MCPServerRepository(db).create_mcp_server(
        MCPServerCreate.model_validate(_mcp_server_payload())
    )


def test_attach_mcp_server(client: TestClient, existing_config, existing_server):
    r = client.post(
        f"/model-configs/{existing_config.id}/mcp-servers",
        json={"server_id": str(existing_server.id)},
    )
    assert r.status_code == 200


def test_attach_mcp_server_idempotent(
    client: TestClient, existing_config, existing_server
):
    url = f"/model-configs/{existing_config.id}/mcp-servers"
    body = {"server_id": str(existing_server.id)}
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json=body).status_code == 200


def test_attach_mcp_server_not_found(client: TestClient, existing_config):
    r = client.post(
        f"/model-configs/{existing_config.id}/mcp-servers",
        json={"server_id": str(uuid4())},
    )
    assert r.status_code == 404


def test_attach_mcp_server_config_not_found(client: TestClient, existing_server):
    r = client.post(
        f"/model-configs/{uuid4()}/mcp-servers",
        json={"server_id": str(existing_server.id)},
    )
    assert r.status_code == 404


def test_detach_mcp_server(client: TestClient, existing_config, existing_server):
    client.post(
        f"/model-configs/{existing_config.id}/mcp-servers",
        json={"server_id": str(existing_server.id)},
    )
    r = client.delete(
        f"/model-configs/{existing_config.id}/mcp-servers/{existing_server.id}"
    )
    assert r.status_code == 204


def test_detach_mcp_server_not_attached(
    client: TestClient, existing_config, existing_server
):
    r = client.delete(
        f"/model-configs/{existing_config.id}/mcp-servers/{existing_server.id}"
    )
    assert r.status_code == 404


def test_list_attached_mcp_servers(
    client: TestClient, existing_config, existing_server
):
    client.post(
        f"/model-configs/{existing_config.id}/mcp-servers",
        json={"server_id": str(existing_server.id)},
    )
    r = client.get(f"/model-configs/{existing_config.id}/mcp-servers")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    ids = {item["id"] for item in data["items"]}
    assert str(existing_server.id) in ids


def test_list_attached_mcp_servers_excludes_soft_deleted(
    client: TestClient, existing_config, existing_server, db: Session
):
    client.post(
        f"/model-configs/{existing_config.id}/mcp-servers",
        json={"server_id": str(existing_server.id)},
    )
    MCPServerRepository(db).delete_mcp_server(existing_server.id)

    r = client.get(f"/model-configs/{existing_config.id}/mcp-servers")
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()["items"]}
    assert str(existing_server.id) not in ids


def test_list_attached_mcp_servers_empty(client: TestClient, existing_config):
    r = client.get(f"/model-configs/{existing_config.id}/mcp-servers")
    assert r.status_code == 200
    assert r.json()["total"] == 0
