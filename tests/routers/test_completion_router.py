import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository


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
    prompt = SystemPromptRepository(db).create_prompt(
        name="completion-test-prompt",
        initial_content="You are a concise assistant.",
    )
    return ModelConfigRepository(db).create(
        {
            "slug": "with-system-prompt",
            "name": "With System Prompt",
            "provider": "openai",
            "model": "gpt-4o",
            "system_prompt_id": prompt.id,
            "is_default": False,
        }
    )


def _mock_agent_run():
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20

    mock_result = MagicMock()
    mock_result.output = "Hello from the model."
    mock_result.usage = MagicMock(return_value=mock_usage)
    return mock_result


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("app.inference.model.log_completion_usage") as m:
        m.delay = MagicMock()
        yield m


@pytest.fixture(autouse=True)
def mock_openai_api_key():
    """Inject a fake API key into the adapter so no real key is required."""
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


def test_completion_uses_default_chat_config_not_embedding_default(
    client: TestClient, db: Session, default_config
):
    """Regression test for PRD 0019: no-model completion must resolve the
    default 'chat' config specifically, not whichever config_type happens to
    be default (get_default() was unscoped by config_type)."""
    ModelConfigRepository(db).create(
        {
            "slug": "default-embedding",
            "name": "Default Embedding",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "config_type": "embedding",
            "params": {"chunk_size": 500, "chunk_overlap": 0, "strategy": "fixed_size"},
            "is_default": True,
        }
    )

    response = client.post(
        "/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 200
    assert response.json()["model"] == default_config.slug


def test_completion_rejects_explicit_embedding_typed_slug(
    client: TestClient, db: Session
):
    ModelConfigRepository(db).create(
        {
            "slug": "embedding-config",
            "name": "Embedding Config",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "config_type": "embedding",
            "params": {"chunk_size": 500, "chunk_overlap": 0, "strategy": "fixed_size"},
        }
    )

    response = client.post(
        "/chat/completions",
        json={
            "model": "embedding-config",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 422


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


def test_completion_missing_messages_returns_422(client: TestClient, default_config):
    response = client.post(
        "/chat/completions",
        json={"model": default_config.slug},
    )

    assert response.status_code == 422
