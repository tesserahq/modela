import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository


@pytest.fixture
def config_payload():
    return {
        "slug": "router-test-model",
        "name": "Router Test Model",
        "provider": "openai",
        "model": "gpt-4o",
        "is_default": False,
    }


@pytest.fixture
def existing_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "existing-router",
            "name": "Existing",
            "provider": "openai",
            "model": "gpt-4o",
        }
    )


def test_create_model_config(client: TestClient, config_payload):
    response = client.post("/model-configs", json=config_payload)

    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == config_payload["slug"]
    assert data["provider"] == "openai"
    assert "id" in data


def test_list_model_configs(client: TestClient, existing_config):
    response = client.get("/model-configs")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert any(item["slug"] == "existing-router" for item in data["items"])


def test_get_model_config(client: TestClient, existing_config):
    response = client.get(f"/model-configs/{existing_config.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(existing_config.id)
    assert response.json()["slug"] == existing_config.slug


def test_get_model_config_not_found(client: TestClient):
    response = client.get(f"/model-configs/{uuid4()}")

    assert response.status_code == 404


def test_update_model_config(client: TestClient, existing_config):
    response = client.put(
        f"/model-configs/{existing_config.id}",
        json={"name": "Renamed", "max_tokens": 512},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Renamed"
    assert data["max_tokens"] == 512


def test_update_model_config_not_found(client: TestClient):
    response = client.put(f"/model-configs/{uuid4()}", json={"name": "X"})

    assert response.status_code == 404


def test_delete_model_config(client: TestClient, existing_config):
    response = client.delete(f"/model-configs/{existing_config.id}")

    assert response.status_code == 204


def test_delete_model_config_not_found(client: TestClient):
    response = client.delete(f"/model-configs/{uuid4()}")

    assert response.status_code == 404


def test_create_sets_default_clears_previous(
    client: TestClient, existing_config, db: Session
):
    client.put(f"/model-configs/{existing_config.id}", json={"is_default": True})

    response = client.post(
        "/model-configs",
        json={
            "slug": "new-default",
            "name": "New Default",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        },
    )

    assert response.status_code == 201
    previous = ModelConfigRepository(db).get_by_slug(existing_config.slug)
    assert previous.is_default is False


def test_create_model_config_invalid_payload_returns_422(client: TestClient):
    response = client.post(
        "/model-configs",
        json={"slug": "x", "name": "Missing provider and model fields"},
    )

    assert response.status_code == 422


def test_list_model_configs_response_is_paginated(client: TestClient, existing_config):
    response = client.get("/model-configs")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
