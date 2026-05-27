import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.schemas.completion_request import CompletionRequestCreate


def _record_payload(**overrides):
    base = dict(
        request_id=str(uuid4()),
        project_id="*",
        model_config_slug="default-chat",
        provider="openai",
        model="gpt-4o",
        input_tokens=10,
        output_tokens=5,
        latency_ms=123,
        cost_estimate_usd=0,
        finish_reason="stop",
    )
    base.update(overrides)
    return CompletionRequestCreate(**base)


@pytest.fixture
def existing_request(db: Session):
    return CompletionRequestRepository(db).create(_record_payload())


def test_list_completion_requests_returns_paginated(client: TestClient, db: Session):
    repo = CompletionRequestRepository(db)
    a = repo.create(_record_payload())
    b = repo.create(_record_payload())

    response = client.get("/completion-requests")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    ids = {item["id"] for item in data["items"]}
    assert str(a.id) in ids
    assert str(b.id) in ids


def test_list_completion_requests_filters_by_project_id(
    client: TestClient, db: Session
):
    repo = CompletionRequestRepository(db)
    target = repo.create(_record_payload(project_id="proj-a"))
    other = repo.create(_record_payload(project_id="proj-b"))

    response = client.get("/completion-requests", params={"project_id": "proj-a"})

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert str(target.id) in ids
    assert str(other.id) not in ids


def test_get_completion_request_by_id(client: TestClient, existing_request):
    response = client.get(f"/completion-requests/{existing_request.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(existing_request.id)
    assert data["request_id"] == existing_request.request_id
    assert data["provider"] == existing_request.provider
    assert data["model"] == existing_request.model


def test_get_completion_request_not_found(client: TestClient):
    response = client.get(f"/completion-requests/{uuid4()}")

    assert response.status_code == 404


def test_list_completion_requests_empty(client: TestClient):
    response = client.get("/completion-requests")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
