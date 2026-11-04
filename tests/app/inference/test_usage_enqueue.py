import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.inference.model import ModelaModel


def _model(inner):
    config = MagicMock()
    config.slug = "default-scan"
    config.provider = "openai"
    config.model = "gpt-4o"
    config.temperature = None
    config.max_tokens = None
    config.top_p = None
    return ModelaModel(
        inner,
        config,
        project_id="project-123",
        request_id="request-123",
    )


def _expected_usage_kwargs():
    return {
        "request_id": "request-123",
        "project_id": "project-123",
        "model_config_slug": "default-scan",
        "provider": "openai",
        "model": "gpt-4o",
        "input_tokens": 17,
        "output_tokens": 5,
        "finish_reason": None,
        "created_by_id": None,
    }


def _assert_publish_off_loop_thread(published, loop_thread):
    assert len(published) == 1
    publish_thread, kwargs = published[0]
    assert publish_thread is not loop_thread
    assert {key: value for key, value in kwargs.items() if key != "latency_ms"} == (
        _expected_usage_kwargs()
    )
    assert isinstance(kwargs["latency_ms"], int)


@pytest.mark.asyncio
async def test_request_enqueues_usage_off_event_loop_thread():
    inner = MagicMock()
    response = MagicMock()
    response.usage.input_tokens = 17
    response.usage.output_tokens = 5
    inner.request = AsyncMock(return_value=response)
    loop_thread = threading.current_thread()
    published = []

    def publish(**kwargs):
        published.append((threading.current_thread(), kwargs))

    with patch("app.inference.model.log_completion_usage") as usage_task:
        usage_task.delay.side_effect = publish
        await _model(inner).request([], None, MagicMock())

    _assert_publish_off_loop_thread(published, loop_thread)


@pytest.mark.asyncio
async def test_request_stream_enqueues_usage_off_event_loop_thread():
    inner = MagicMock()
    stream = SimpleNamespace(usage=SimpleNamespace(input_tokens=17, output_tokens=5))

    @asynccontextmanager
    async def request_stream(*args, **kwargs):
        yield stream

    inner.request_stream = request_stream
    loop_thread = threading.current_thread()
    published = []

    def publish(**kwargs):
        published.append((threading.current_thread(), kwargs))

    with patch("app.inference.model.log_completion_usage") as usage_task:
        usage_task.delay.side_effect = publish
        async with _model(inner).request_stream([], None, MagicMock()):
            pass

    _assert_publish_off_loop_thread(published, loop_thread)
