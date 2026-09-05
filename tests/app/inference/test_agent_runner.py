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


class TestAgentRunnerRunStream:
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
