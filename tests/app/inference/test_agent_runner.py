import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_result(output="response text", input_tokens=5, output_tokens=10):
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    result = MagicMock()
    result.output = output
    result.usage = MagicMock(return_value=usage)
    return result


def _make_agent_mock(run_return=None, stream_result=None):
    """Return a mock Agent instance with run/run_stream pre-configured."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_return or _make_mock_result())

    if stream_result is not None:
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=stream_result)
        ctx.__aexit__ = AsyncMock(return_value=False)
        agent.run_stream = MagicMock(return_value=ctx)

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
    async def test_run_stream_passes_retries_kwarg(self, runner):
        async def fake_stream_text(delta):
            yield "chunk"

        stream_result = MagicMock()
        stream_result.stream_text = fake_stream_text
        agent = _make_agent_mock(stream_result=stream_result)

        with patch("app.inference.agent_runner.Agent", return_value=agent):
            chunks = [c async for c in runner.run_stream("hello", max_result_retries=5)]

        _, kwargs = agent.run_stream.call_args
        assert kwargs.get("output_retries") == 5
        assert "retries" not in kwargs
        assert chunks == ["chunk"]

    @pytest.mark.asyncio
    async def test_run_stream_omits_retries_when_none(self, runner):
        async def fake_stream_text(delta):
            yield "chunk"

        stream_result = MagicMock()
        stream_result.stream_text = fake_stream_text
        agent = _make_agent_mock(stream_result=stream_result)

        with patch("app.inference.agent_runner.Agent", return_value=agent):
            chunks = [c async for c in runner.run_stream("hello")]

        _, kwargs = agent.run_stream.call_args
        assert "output_retries" not in kwargs
        assert "retries" not in kwargs
