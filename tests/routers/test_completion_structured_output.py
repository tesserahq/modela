import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic_ai.exceptions import UnexpectedModelBehavior
from sqlalchemy.orm import Session

from app.repositories.model_config_repository import ModelConfigRepository

SENTIMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "confidence": {"type": "number"},
    },
    "required": ["sentiment", "confidence"],
}


@pytest.fixture
def config_with_output_schema(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "structured-gpt-4o",
            "name": "Structured GPT-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
            "output_schema": SENTIMENT_SCHEMA,
        }
    )


@pytest.fixture
def config_without_schema(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "plain-gpt-4o",
            "name": "Plain GPT-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
        }
    )


@pytest.fixture(autouse=True)
def mock_openai_api_key():
    mock_settings = MagicMock()
    mock_settings.openai_api_key = "sk-test-fake-key"
    with patch(
        "app.inference.adapters.openai.get_settings", return_value=mock_settings
    ):
        yield


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("app.inference.model.log_completion_usage") as m:
        m.delay = MagicMock()
        yield m


def _make_usage():
    usage = MagicMock()
    usage.input_tokens = 10
    usage.output_tokens = 20
    return usage


def test_structured_output_returns_dict_in_content(
    client: TestClient, config_with_output_schema
):
    class SentimentOutput(BaseModel):
        sentiment: str
        confidence: float

    mock_result = MagicMock()
    mock_result.output = SentimentOutput(sentiment="positive", confidence=0.91)
    mock_result.usage.return_value = _make_usage()

    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        response = client.post(
            "/chat/completions",
            json={
                "model": config_with_output_schema.slug,
                "messages": [{"role": "user", "content": "Analyse this review."}],
            },
        )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == {"sentiment": "positive", "confidence": 0.91}


def test_plain_config_still_returns_string_content(
    client: TestClient, config_without_schema
):
    mock_result = MagicMock()
    mock_result.output = "Hello from the model."
    mock_result.usage.return_value = _make_usage()

    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        response = client.post(
            "/chat/completions",
            json={
                "model": config_without_schema.slug,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 200
    assert (
        response.json()["choices"][0]["message"]["content"] == "Hello from the model."
    )


def test_provider_validation_failure_returns_502(
    client: TestClient, config_with_output_schema
):
    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
        side_effect=UnexpectedModelBehavior("Validation failed", body="bad json"),
    ):
        response = client.post(
            "/chat/completions",
            json={
                "model": config_with_output_schema.slug,
                "messages": [{"role": "user", "content": "Analyse this review."}],
            },
        )

    assert response.status_code == 502
    body = response.json()
    assert "conform" in body["detail"].lower() or "schema" in body["detail"].lower()
    assert isinstance(body["validation_errors"], list)
    assert "raw_content" in body


def test_invalid_output_schema_on_model_config_returns_422(
    client: TestClient, db: Session
):
    config = ModelConfigRepository(db).create(
        {
            "slug": "bad-schema-config",
            "name": "Bad Schema Config",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
            "output_schema": {"type": "string"},
        }
    )

    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
    ):
        response = client.post(
            "/chat/completions",
            json={
                "model": config.slug,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 422


def test_unsupported_schema_keyword_returns_422(client: TestClient, db: Session):
    config = ModelConfigRepository(db).create(
        {
            "slug": "ref-schema-config",
            "name": "Ref Schema Config",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
            "output_schema": {
                "type": "object",
                "properties": {"value": {"$ref": "#/definitions/Foo"}},
            },
        }
    )

    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
    ):
        response = client.post(
            "/chat/completions",
            json={
                "model": config.slug,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 422
