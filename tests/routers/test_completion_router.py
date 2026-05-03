import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository


@pytest.fixture
def default_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "test-gpt-4o",
            "name": "Test GPT-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        }
    )


@pytest.fixture
def config_with_system_prompt(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "with-system-prompt",
            "name": "With System Prompt",
            "provider": "openai",
            "model": "gpt-4o",
            "system_prompt": "You are a concise assistant.",
            "is_default": False,
        }
    )


def _mock_agent_run():
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20

    mock_result = MagicMock()
    mock_result.output = "Hello from the model."
    mock_result.usage.return_value = mock_usage
    return mock_result


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("app.gateway.modela_model.log_completion_usage") as m:
        m.delay = MagicMock()
        yield m


@pytest.fixture(autouse=True)
def mock_openai_api_key():
    """Inject a fake API key into the adapter so no real key is required."""
    mock_settings = MagicMock()
    mock_settings.openai_api_key = "sk-test-fake-key"
    with patch(
        "app.providers.openai_adapter.get_settings",
        return_value=mock_settings,
    ):
        yield


@pytest.fixture(autouse=True)
def mock_agent_run():
    with patch(
        "app.commands.completions.create_completion_command.Agent.run",
        new_callable=AsyncMock,
        return_value=_mock_agent_run(),
    ):
        yield


def test_completion_valid_slug(client: TestClient, default_config):
    response = client.post(
        "/chat/completions",
        json={
            "model": default_config.slug,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == default_config.slug
    assert data["choices"][0]["message"]["content"] == "Hello from the model."
    assert data["object"] == "chat.completion"
    assert "X-Modela-Config-Slug" in response.headers
    assert "X-Modela-Request-Id" in response.headers


def test_completion_unknown_slug(client: TestClient):
    response = client.post(
        "/chat/completions",
        json={
            "model": "nonexistent-model",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 404


def test_completion_uses_default_config(client: TestClient, default_config):
    response = client.post(
        "/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == default_config.slug


def test_completion_no_model_no_default(client: TestClient):
    response = client.post(
        "/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 404


def test_completion_with_system_prompt(client: TestClient, config_with_system_prompt):
    response = client.post(
        "/chat/completions",
        json={
            "model": config_with_system_prompt.slug,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 200


def test_completion_usage_in_response(client: TestClient, default_config):
    response = client.post(
        "/chat/completions",
        json={
            "model": default_config.slug,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    data = response.json()
    assert data["usage"]["prompt_tokens"] == 10
    assert data["usage"]["completion_tokens"] == 20
    assert data["usage"]["total_tokens"] == 30
