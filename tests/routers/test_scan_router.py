import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "document_number": {"type": "string"},
        "date_of_birth": {"type": "string"},
    },
    "required": ["full_name", "document_number"],
}


@pytest.fixture
def default_scan_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "default-scan",
            "name": "Default Scan",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "scan",
            "is_default": True,
            "output_schema": _OUTPUT_SCHEMA,
        }
    )


@pytest.fixture
def explicit_scan_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "explicit-scan",
            "name": "Explicit Scan",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "scan",
            "is_default": False,
            "output_schema": _OUTPUT_SCHEMA,
        }
    )


@pytest.fixture
def scan_config_without_schema(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "scan-no-schema",
            "name": "Scan Without Schema",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "scan",
            "is_default": False,
        }
    )


@pytest.fixture
def scan_config_with_system_prompt(db: Session):
    prompt = SystemPromptRepository(db).create_prompt(
        name="scan-prompt",
        initial_content="Extract fields from the identity document.",
    )
    return ModelConfigRepository(db).create(
        {
            "slug": "scan-with-prompt",
            "name": "Scan With Prompt",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "scan",
            "is_default": False,
            "output_schema": _OUTPUT_SCHEMA,
            "system_prompt_id": prompt.id,
        }
    )


def _mock_agent_run():
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20

    mock_result = MagicMock()
    mock_result.output = MagicMock()
    mock_result.output.model_dump.return_value = {
        "full_name": "Jane Doe",
        "document_number": "X1234567",
        "date_of_birth": "1990-01-15",
    }
    mock_result.usage.return_value = mock_usage
    return mock_result


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("app.inference.model.log_completion_usage") as m:
        m.delay = MagicMock()
        yield m


@pytest.fixture(autouse=True)
def mock_openai_api_key():
    mock_settings = MagicMock()
    mock_settings.openai_api_key = "sk-test-fake-key"
    with patch(
        "app.inference.adapters.openai.get_settings",
        return_value=mock_settings,
    ):
        yield


@pytest.fixture(autouse=True)
def mock_agent_run():
    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
        return_value=_mock_agent_run(),
    ):
        yield


# --- /scan/file tests ---


def test_scan_file_with_default_config(client: TestClient, default_scan_config):
    response = client.post(
        "/scan/file",
        json={"file_url": "https://example.com/passport.pdf"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["full_name"] == "Jane Doe"
    assert data["data"]["document_number"] == "X1234567"
    assert data["model"] == default_scan_config.slug
    assert "request_id" in data


def test_scan_file_with_explicit_slug(client: TestClient, explicit_scan_config):
    response = client.post(
        "/scan/file",
        json={
            "file_url": "https://example.com/passport.pdf",
            "model": explicit_scan_config.slug,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == explicit_scan_config.slug


def test_scan_file_with_explicit_mime_type(client: TestClient, default_scan_config):
    response = client.post(
        "/scan/file",
        json={
            "file_url": "https://example.com/id.jpg",
            "mime_type": "image/jpeg",
        },
    )

    assert response.status_code == 200


def test_scan_file_with_system_prompt(
    client: TestClient, scan_config_with_system_prompt
):
    response = client.post(
        "/scan/file",
        json={
            "file_url": "https://example.com/passport.pdf",
            "model": scan_config_with_system_prompt.slug,
        },
    )

    assert response.status_code == 200


def test_scan_file_no_output_schema_returns_422(
    client: TestClient, scan_config_without_schema
):
    response = client.post(
        "/scan/file",
        json={
            "file_url": "https://example.com/passport.pdf",
            "model": scan_config_without_schema.slug,
        },
    )

    assert response.status_code == 422


def test_scan_file_unknown_slug(client: TestClient):
    response = client.post(
        "/scan/file",
        json={"file_url": "https://example.com/passport.pdf", "model": "nonexistent"},
    )

    assert response.status_code == 404


def test_scan_file_no_default_config(client: TestClient):
    response = client.post(
        "/scan/file",
        json={"file_url": "https://example.com/passport.pdf"},
    )

    assert response.status_code == 404


def test_scan_file_missing_file_url_returns_422(
    client: TestClient, default_scan_config
):
    response = client.post("/scan/file", json={})

    assert response.status_code == 422
