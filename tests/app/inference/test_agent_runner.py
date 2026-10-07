import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelResponse,
    PartStartEvent,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset

from app.exceptions.provider_errors import ProviderTimeoutError
from app.inference.agent_runner import StreamedEvent


def _make_mock_result(output="response text", input_tokens=5, output_tokens=10):
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    result = MagicMock()
    result.output = output
    result.usage = MagicMock(return_value=usage)
    return result


def _make_agent_mock(run_return=None, stream_chunks=None):
    """Return a mock Agent instance with run/run_stream_events pre-configured."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_return or _make_mock_result())

    if stream_chunks is not None:

        async def events():
            for chunk in stream_chunks:
                yield PartStartEvent(index=0, part=TextPart(chunk))

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=events())
        ctx.__aexit__ = AsyncMock(return_value=False)
        agent.run_stream_events = MagicMock(return_value=ctx)

    return agent


@pytest.fixture
def runner():
    from app.inference.agent_runner import AgentRunner

    return AgentRunner(MagicMock())


class TestAgentRunnerRun:
    @pytest.mark.asyncio
    async def test_run_passes_retries_kwarg(self, runner):
        agent = _make_agent_mock()
        with patch("app.inference.agent_runner.Agent", return_value=agent):
            await runner.run("hello", max_result_retries=3)

        _, kwargs = agent.run.call_args
        assert kwargs.get("output_retries") == 3
        assert "retries" not in kwargs

    @pytest.mark.asyncio
    async def test_run_omits_retries_when_none(self, runner):
        agent = _make_agent_mock()
        with patch("app.inference.agent_runner.Agent", return_value=agent):
            await runner.run("hello")

        _, kwargs = agent.run.call_args
        assert "output_retries" not in kwargs
        assert "retries" not in kwargs

    @pytest.mark.asyncio
    async def test_run_passes_message_history(self, runner):
        agent = _make_agent_mock()
        history = [MagicMock()]
        with patch("app.inference.agent_runner.Agent", return_value=agent):
            await runner.run("hello", message_history=history)

        _, kwargs = agent.run.call_args
        assert history[0] in kwargs["message_history"]

    @pytest.mark.asyncio
    async def test_run_returns_agent_result(self, runner):
        agent = _make_agent_mock(
            run_return=_make_mock_result(output="hi", input_tokens=2, output_tokens=4)
        )
        with patch("app.inference.agent_runner.Agent", return_value=agent):
            result = await runner.run("hello")

        assert result.output == "hi"
        assert result.input_tokens == 2
        assert result.output_tokens == 4

    @pytest.mark.asyncio
    async def test_run_classifies_provider_timeout(self, runner):
        agent = _make_agent_mock()
        agent.run.side_effect = TimeoutError("provider timed out")
        with (
            patch("app.inference.agent_runner.Agent", return_value=agent),
            pytest.raises(ProviderTimeoutError, match="provider timed out"),
        ):
            await runner.run("hello")


class TestAgentRunnerRunStream:
    @pytest.mark.asyncio
    async def test_run_stream_drains_committed_events_before_later_failure(
        self, runner
    ):
        recorded = [{"id": "evt-1"}]

        @asynccontextmanager
        async def failing_stream(*args, **kwargs):
            async def events():
                raise RuntimeError("later provider failure")
                yield  # pragma: no cover - makes this an async generator

            yield events()

        agent = _make_agent_mock()
        agent.run_stream_events = failing_stream

        def drain_events():
            pending = list(recorded)
            recorded.clear()
            return pending

        with patch("app.inference.agent_runner.Agent", return_value=agent):
            stream = runner.run_stream("hello", drain_events=drain_events)
            assert await anext(stream) == StreamedEvent({"id": "evt-1"})
            with pytest.raises(RuntimeError, match="later provider failure"):
                await anext(stream)

    @pytest.mark.asyncio
    async def test_run_stream_disconnect_does_not_retry_event_delivery(self, runner):
        drain_events = MagicMock(return_value=[])

        @asynccontextmanager
        async def cancelled_stream(*args, **kwargs):
            async def events():
                raise asyncio.CancelledError
                yield  # pragma: no cover - makes this an async generator

            yield events()

        agent = _make_agent_mock()
        agent.run_stream_events = cancelled_stream

        with (
            patch("app.inference.agent_runner.Agent", return_value=agent),
            pytest.raises(asyncio.CancelledError),
        ):
            async for _ in runner.run_stream("hello", drain_events=drain_events):
                pass

        # A cancelled transport is no longer writable. Delivery remains
        # best-effort rather than consuming records that no client can see.
        drain_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_stream_completes_tool_loop_after_preamble(self):
        tool_calls = []

        def lookup(value: int) -> int:
            tool_calls.append(value)
            return value * 2

        class PreambleThenToolModel(TestModel):
            def _request(self, messages, model_settings, model_request_parameters):
                if any(
                    isinstance(part, ToolReturnPart)
                    for message in messages
                    for part in message.parts
                ):
                    return ModelResponse(parts=[TextPart("final answer")])
                return ModelResponse(
                    parts=[
                        TextPart("preamble"),
                        ToolCallPart("lookup", {"value": 3}, "call-1"),
                    ]
                )

        from app.inference.agent_runner import AgentRunner

        chunks = [
            chunk
            async for chunk in AgentRunner(PreambleThenToolModel()).run_stream(
                "go", toolsets=[FunctionToolset([lookup])]
            )
        ]

        assert "".join(chunks) == "preamblefinal answer"
        assert tool_calls == [3]

    @pytest.mark.asyncio
    async def test_run_stream_interleaves_drained_events_after_tool_result(self):
        recorded: list[dict] = []
        drained = 0

        def lookup(value: int) -> int:
            # Stands in for an MCP tool recording a committed domain event.
            recorded.append({"id": "evt-1"})
            return value * 2

        def drain_events() -> list[dict]:
            nonlocal drained
            pending = recorded[drained:]
            drained = len(recorded)
            return pending

        class PreambleThenToolModel(TestModel):
            def _request(self, messages, model_settings, model_request_parameters):
                if any(
                    isinstance(part, ToolReturnPart)
                    for message in messages
                    for part in message.parts
                ):
                    return ModelResponse(parts=[TextPart("final answer")])
                return ModelResponse(
                    parts=[
                        TextPart("preamble"),
                        ToolCallPart("lookup", {"value": 3}, "call-1"),
                    ]
                )

        from app.inference.agent_runner import AgentRunner

        items = [
            item
            async for item in AgentRunner(PreambleThenToolModel()).run_stream(
                "go",
                toolsets=[FunctionToolset([lookup])],
                drain_events=drain_events,
            )
        ]

        event_index = items.index(StreamedEvent({"id": "evt-1"}))
        assert "".join(items[:event_index]) == "preamble"
        assert "".join(items[event_index + 1 :]) == "final answer"
        assert sum(isinstance(item, StreamedEvent) for item in items) == 1

    @pytest.mark.asyncio
    async def test_run_stream_passes_retries_kwarg(self, runner):
        agent = _make_agent_mock(stream_chunks=["chunk"])

        with patch("app.inference.agent_runner.Agent", return_value=agent):
            chunks = [c async for c in runner.run_stream("hello", max_result_retries=5)]

        _, kwargs = agent.run_stream_events.call_args
        assert kwargs.get("output_retries") == 5
        assert "retries" not in kwargs
        assert chunks == ["chunk"]

    @pytest.mark.asyncio
    async def test_run_stream_omits_retries_when_none(self, runner):
        agent = _make_agent_mock(stream_chunks=["chunk"])

        with patch("app.inference.agent_runner.Agent", return_value=agent):
            [c async for c in runner.run_stream("hello")]

        _, kwargs = agent.run_stream_events.call_args
        assert "output_retries" not in kwargs
        assert "retries" not in kwargs
