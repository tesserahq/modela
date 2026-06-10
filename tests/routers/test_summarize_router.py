import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository


@pytest.fixture
def default_summary_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "default-summary",
            "name": "Default Summary",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "summary",
            "is_default": True,
        }
    )


@pytest.fixture
def explicit_summary_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "explicit-summary",
            "name": "Explicit Summary",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "summary",
            "is_default": False,
        }
    )


@pytest.fixture
def summary_config_with_system_prompt(db: Session):
    prompt = SystemPromptRepository(db).create_prompt(
        name="summarize-prompt",
        initial_content="Provide a detailed summary.",
    )
    return ModelConfigRepository(db).create(
        {
            "slug": "summary-with-prompt",
            "name": "Summary With Prompt",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "summary",
            "system_prompt_id": prompt.id,
            "is_default": False,
        }
    )


def _mock_agent_run():
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20

    mock_result = MagicMock()
    mock_result.output = "This is a summary."
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


# --- /summarize/text tests ---


def test_summarize_text_with_default_config(client: TestClient, default_summary_config):
    response = client.post(
        "/summarize/text",
        json={"content": "A long document about something interesting."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "This is a summary."
    assert data["model"] == default_summary_config.slug
    assert "request_id" in data


def test_summarize_text_with_explicit_slug(client: TestClient, explicit_summary_config):
    response = client.post(
        "/summarize/text",
        json={
            "content": "A long document about something interesting.",
            "model": explicit_summary_config.slug,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == explicit_summary_config.slug


def test_summarize_text_unknown_slug(client: TestClient):
    response = client.post(
        "/summarize/text",
        json={"content": "Some text.", "model": "nonexistent-config"},
    )

    assert response.status_code == 404


def test_summarize_text_no_default_config(client: TestClient):
    response = client.post(
        "/summarize/text",
        json={"content": "Some text."},
    )

    assert response.status_code == 404


def test_summarize_text_missing_content_returns_422(
    client: TestClient, default_summary_config
):
    response = client.post("/summarize/text", json={})

    assert response.status_code == 422


def test_summarize_text_with_system_prompt(
    client: TestClient, summary_config_with_system_prompt
):
    response = client.post(
        "/summarize/text",
        json={
            "content": "Some document text.",
            "model": summary_config_with_system_prompt.slug,
        },
    )

    assert response.status_code == 200


# --- /summarize/file tests ---


def test_summarize_file_with_default_config(client: TestClient, default_summary_config):
    response = client.post(
        "/summarize/file",
        json={"file_url": "https://example.com/doc.pdf"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "This is a summary."
    assert data["model"] == default_summary_config.slug
    assert "request_id" in data


def test_summarize_file_with_explicit_slug(client: TestClient, explicit_summary_config):
    response = client.post(
        "/summarize/file",
        json={
            "file_url": "https://example.com/doc.pdf",
            "model": explicit_summary_config.slug,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == explicit_summary_config.slug


def test_summarize_file_with_explicit_mime_type(
    client: TestClient, default_summary_config
):
    response = client.post(
        "/summarize/file",
        json={
            "file_url": "https://example.com/presigned-s3-url",
            "mime_type": "application/pdf",
        },
    )

    assert response.status_code == 200


def test_summarize_file_with_image_mime_type(
    client: TestClient, default_summary_config
):
    response = client.post(
        "/summarize/file",
        json={
            "file_url": "https://example.com/photo.jpg",
            "mime_type": "image/jpeg",
        },
    )

    assert response.status_code == 200


def test_summarize_file_unknown_slug(client: TestClient):
    response = client.post(
        "/summarize/file",
        json={"file_url": "https://example.com/doc.pdf", "model": "nonexistent-config"},
    )

    assert response.status_code == 404


def test_summarize_file_no_default_config(client: TestClient):
    response = client.post(
        "/summarize/file",
        json={"file_url": "https://example.com/doc.pdf"},
    )

    assert response.status_code == 404


def test_summarize_file_missing_file_url_returns_422(
    client: TestClient, default_summary_config
):
    response = client.post("/summarize/file", json={})

    assert response.status_code == 422
