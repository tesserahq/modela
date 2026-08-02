from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.inference.model import ModelaModel


@pytest.fixture
def span_exporter(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    from app.inference import model as model_module

    monkeypatch.setattr(
        model_module,
        "tracer",
        provider.get_tracer("tests.inference.model"),
        raising=False,
    )
    return exporter


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


def _response():
    usage = MagicMock()
    usage.input_tokens = 17
    usage.output_tokens = 5
    response = MagicMock()
    response.usage = usage
    return response


@pytest.mark.asyncio
async def test_model_request_span_records_safe_metadata(span_exporter):
    inner = MagicMock()
    inner.request = AsyncMock(return_value=_response())
    messages = ["private prompt", "https://files.example/secret?token=credential"]

    with patch("app.inference.model.log_completion_usage") as usage_task:
        await _model(inner).request(messages, None, MagicMock())

    usage_task.delay.assert_called_once()
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "inference.model.request"
    assert span.attributes["gen_ai.provider.name"] == "openai"
    assert span.attributes["gen_ai.request.model"] == "gpt-4o"
    assert span.attributes["modela.model_config.slug"] == "default-scan"
    assert span.attributes["modela.request.attempt"] == 1
    assert span.attributes["gen_ai.usage.input_tokens"] == 17
    assert span.attributes["gen_ai.usage.output_tokens"] == 5
    serialized_attributes = repr(dict(span.attributes))
    assert "private prompt" not in serialized_attributes
    assert "credential" not in serialized_attributes


@pytest.mark.asyncio
async def test_model_request_span_numbers_structured_output_retries(span_exporter):
    inner = MagicMock()
    inner.request = AsyncMock(side_effect=[_response(), _response()])
    model = _model(inner)

    with patch("app.inference.model.log_completion_usage"):
        await model.request([], None, MagicMock())
        await model.request([], None, MagicMock())

    spans = span_exporter.get_finished_spans()
    assert [span.attributes["modela.request.attempt"] for span in spans] == [1, 2]


@pytest.mark.asyncio
async def test_model_request_span_records_provider_errors(span_exporter):
    inner = MagicMock()
    inner.request = AsyncMock(side_effect=TimeoutError("provider timed out"))

    with pytest.raises(TimeoutError, match="provider timed out"):
        await _model(inner).request([], None, MagicMock())

    span = span_exporter.get_finished_spans()[0]
    assert span.status.is_ok is False
    assert span.attributes["error.type"] == "TimeoutError"
    assert span.events == ()
    assert "provider timed out" not in repr(dict(span.attributes))


@pytest.mark.asyncio
async def test_agent_run_emits_orchestration_span(monkeypatch):
    from app.inference import agent_runner as agent_runner_module

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        agent_runner_module,
        "tracer",
        provider.get_tracer("tests.inference.agent_runner"),
        raising=False,
    )

    agent = MagicMock()
    result = MagicMock()
    result.output = "extracted"
    result.usage.return_value.input_tokens = 3
    result.usage.return_value.output_tokens = 2
    agent.run = AsyncMock(return_value=result)

    with patch("app.inference.agent_runner.Agent", return_value=agent):
        await agent_runner_module.AgentRunner(MagicMock()).run(
            ["private prompt"],
            system_prompt="private system prompt",
            output_type=None,
        )

    span = exporter.get_finished_spans()[0]
    assert span.name == "inference.agent.run"
    assert span.attributes["modela.inference.structured_output"] is False
    assert "private prompt" not in repr(dict(span.attributes))


@pytest.mark.asyncio
async def test_scan_command_emits_safe_scan_span(monkeypatch):
    from app.commands.scan import create_scan_command as scan_module

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        scan_module,
        "tracer",
        provider.get_tracer("tests.commands.scan"),
        raising=False,
    )

    config = MagicMock()
    config.slug = "default-scan"
    config.provider = "openai"
    config.model = "gpt-4o"
    config.output_schema = {"private_field": "must not be traced"}
    config.system_prompt_id = None

    command = scan_module.CreateScanCommand(MagicMock())
    command.repo = MagicMock()
    command.repo.get_default_for_type.return_value = config
    agent_result = MagicMock(output={"private_field": "secret"})
    agent_result.input_tokens = 3
    agent_result.output_tokens = 2

    with (
        patch("app.commands.scan.create_scan_command.validate_file_url"),
        patch("app.commands.scan.create_scan_command.schema_to_model"),
        patch("app.commands.scan.create_scan_command.build_model"),
        patch(
            "app.commands.scan.create_scan_command.AgentRunner.run",
            new_callable=AsyncMock,
            return_value=agent_result,
        ),
    ):
        await command.execute_file(
            file_url="https://files.example/private?token=credential",
            mime_type="application/pdf",
            model_slug=None,
            project_id="project-123",
            request_id="request-123",
            user_id=uuid4(),
        )

    span = exporter.get_finished_spans()[0]
    assert span.name == "scan.file"
    assert span.attributes["modela.model_config.slug"] == "default-scan"
    assert span.attributes["gen_ai.provider.name"] == "openai"
    assert span.attributes["gen_ai.request.model"] == "gpt-4o"
    assert span.attributes["scan.mime_type"] == "application/pdf"
    serialized_attributes = repr(dict(span.attributes))
    assert "private_field" not in serialized_attributes
    assert "credential" not in serialized_attributes
