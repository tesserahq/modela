import json
import pytest
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository


@pytest.fixture
def default_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "stream-gpt-4o",
            "name": "Stream GPT-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        }
    )


@pytest.fixture
def config_with_output_schema(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "stream-structured",
            "name": "Structured (stream test)",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
            "output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        }
    )


@pytest.fixture
def config_with_system_prompt(db: Session):
    prompt = SystemPromptRepository(db).create_prompt(
        name="stream-test-prompt",
        initial_content="You are a concise assistant.",
    )
    return ModelConfigRepository(db).create(
        {
            "slug": "stream-with-system-prompt",
            "name": "Stream With System Prompt",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
            "system_prompt_id": prompt.id,
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


def _make_mock_run_stream(chunks: list[str]):
    """Return an asynccontextmanager that yields a StreamedRunResult mock producing `chunks`."""

    async def _stream_text(delta=True):
        for chunk in chunks:
            yield chunk

    mock_result = MagicMock()
    mock_result.stream_text = _stream_text

    @asynccontextmanager
    async def _run_stream(self, *args, **kwargs):
        yield mock_result

    return _run_stream


def _collect_sse(client: TestClient, url: str, payload: dict) -> list[dict]:
    """POST with stream=True and collect all parsed SSE data objects (excluding [DONE])."""
    with client.stream("POST", url, json=payload) as r:
        lines = list(r.iter_lines())
    chunks = []
    for line in lines:
        if line.startswith("data: ") and line != "data: [DONE]":
            chunks.append(json.loads(line[len("data: ") :]))
    return chunks


def test_stream_returns_event_stream_content_type(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello"]),
    ):
        with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]


def test_stream_response_headers_present(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hi"]),
    ):
        with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        ) as r:
            assert "x-modela-config-slug" in r.headers
            assert "x-modela-request-id" in r.headers
            assert r.headers["x-modela-config-slug"] == default_config.slug


def test_stream_chunks_have_openai_format(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello", " world"]),
    ):
        chunks = _collect_sse(
            client,
            "/chat/completions",
            {
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )

    # 2 content chunks + 1 final stop chunk
    assert len(chunks) == 3
    for chunk in chunks:
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["model"] == default_config.slug
        assert len(chunk["choices"]) == 1
        assert chunk["choices"][0]["index"] == 0


def test_stream_first_chunk_has_role(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello", " world"]),
    ):
        chunks = _collect_sse(
            client,
            "/chat/completions",
            {
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )

    first = chunks[0]
    assert first["choices"][0]["delta"]["role"] == "assistant"
    assert first["choices"][0]["delta"]["content"] == "Hello"
    assert first["choices"][0]["finish_reason"] is None


def test_stream_subsequent_chunks_have_no_role(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello", " world"]),
    ):
        chunks = _collect_sse(
            client,
            "/chat/completions",
            {
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )

    second = chunks[1]
    assert (
        "role" not in second["choices"][0]["delta"]
        or second["choices"][0]["delta"].get("role") is None
    )
    assert second["choices"][0]["delta"]["content"] == " world"


def test_stream_final_chunk_has_finish_reason_stop(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello"]),
    ):
        chunks = _collect_sse(
            client,
            "/chat/completions",
            {
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )

    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["choices"][0]["delta"] == {}


def test_stream_ends_with_done(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello"]),
    ):
        with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        ) as r:
            lines = list(r.iter_lines())

    assert "data: [DONE]" in lines


def test_stream_chunks_share_same_id(client: TestClient, default_config):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello", " world"]),
    ):
        chunks = _collect_sse(
            client,
            "/chat/completions",
            {
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )

    ids = {c["id"] for c in chunks}
    assert len(ids) == 1
    assert list(ids)[0].startswith("chatcmpl-")


def test_stream_with_output_schema_returns_422(
    client: TestClient, config_with_output_schema
):
    response = client.post(
        "/chat/completions",
        json={
            "model": config_with_output_schema.slug,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        },
    )
    assert response.status_code == 422


def test_stream_false_returns_standard_response(client: TestClient, default_config):
    """Regression: stream=false must return the non-streaming response unchanged."""
    mock_usage = MagicMock()
    mock_usage.input_tokens = 5
    mock_usage.output_tokens = 10
    mock_result = MagicMock()
    mock_result.output = "Non-streaming response."
    mock_result.usage.return_value = mock_usage

    from unittest.mock import AsyncMock

    with patch(
        "app.inference.agent_runner.Agent.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        response = client.post(
            "/chat/completions",
            json={
                "model": default_config.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "Non-streaming response."


def test_stream_unknown_slug_returns_404(client: TestClient):
    response = client.post(
        "/chat/completions",
        json={
            "model": "nonexistent-slug",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        },
    )
    assert response.status_code == 404


def test_stream_with_system_prompt(client: TestClient, config_with_system_prompt):
    with patch(
        "app.inference.agent_runner.Agent.run_stream",
        _make_mock_run_stream(["Hello"]),
    ):
        with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": config_with_system_prompt.slug,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        ) as r:
            assert r.status_code == 200
