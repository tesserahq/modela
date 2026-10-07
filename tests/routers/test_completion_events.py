"""Chat Completions `events` channel (PRD 0022, issue #104).

These drive a real pydantic-ai agent loop through MCPToolset and
MCPToolExecutor; only the MCP transport, server lookup and credentials are
faked, so metadata parsing and event delivery are exercised end to end.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from fastmcp.client.client import CallToolResult
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel
from sqlalchemy.orm import Session

from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.mcp_tool import MCPCatalogTool
from app.services.mcp.event_collector import CompletionEventCollector
from tests.app.services.mcp.event_fixtures import event_payload, events_meta

TOOL = MCPCatalogTool(
    qualified_name="linden__create_person",
    original_name="create_person",
    server_id="linden",
)
PERSON = {"id": "person-1", "email": "jane@example.com", "phone": "555-0100"}
EVENT = event_payload("evt-1")


def _config(
    db: Session, slug: str, *, expose_events: bool, output_schema: dict | None = None
):
    return ModelConfigRepository(db).create(
        {
            "slug": slug,
            "name": slug,
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
            "expose_events": expose_events,
            "output_schema": output_schema,
        }
    )


@pytest.fixture
def events_config(db: Session):
    return _config(db, "events-enabled", expose_events=True)


@pytest.fixture
def closed_config(db: Session):
    return _config(db, "events-disabled", expose_events=False)


@pytest.fixture(autouse=True)
def mock_openai_api_key():
    settings = MagicMock(openai_api_key="sk-test-fake-key")
    with patch("app.inference.adapters.openai.get_settings", return_value=settings):
        yield


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("app.inference.model.log_completion_usage") as m:
        m.delay = MagicMock()
        yield m


@pytest.fixture
def catalog():
    with patch(
        "app.commands.completions.create_completion_command."
        "MCPToolCatalogRepository.get_tools_for_model_config",
        new=AsyncMock(return_value=[TOOL]),
    ) as get_tools:
        yield get_tools


@pytest.fixture
def mcp_result():
    """Fake the MCP transport; tests set the CallToolResult it returns."""
    client = MagicMock()
    client.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[],
            structured_content=PERSON,
            meta=events_meta(EVENT),
            data=PERSON,
            is_error=False,
        )
    )

    @asynccontextmanager
    async def fake_client_context(url, headers):
        yield client

    server = MagicMock(url="https://mcp.example/mcp", credential_id=None)
    with (
        patch("app.services.mcp.tool_executor.MCPServerRepository") as servers,
        patch("app.services.mcp.tool_executor.CredentialApplier") as creds,
        patch("app.services.mcp.tool_executor.client_context", fake_client_context),
    ):
        servers.return_value.get_mcp_server_by_server_id.return_value = server
        creds.return_value.apply_for_user.return_value = {}
        yield client.call_tool


class CreatePersonModel(TestModel):
    """Calls the MCP tool once, then answers; records what the model saw."""

    def __init__(self):
        super().__init__()
        self.tool_returns: list = []

    def _request(self, messages, model_settings, model_request_parameters):
        for message in messages:
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    self.tool_returns.append(part.content)
                    return ModelResponse(parts=[TextPart("Created Jane.")])
        return ModelResponse(
            parts=[
                TextPart("Creating. "),
                ToolCallPart(TOOL.qualified_name, {"first_name": "Jane"}, "call-1"),
            ]
        )


class FailAfterCreateModel(CreatePersonModel):
    """Commits through the MCP tool, then fails the following model round."""

    def __init__(self, error: Exception):
        super().__init__()
        self.error = error

    def _request(self, messages, model_settings, model_request_parameters):
        if any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        ):
            raise self.error
        return super()._request(messages, model_settings, model_request_parameters)


@pytest.fixture
def model():
    model = CreatePersonModel()
    with patch(
        "app.commands.completions.create_completion_command.build_model",
        return_value=model,
    ):
        yield model


def _post(client, config, **extra):
    return client.post(
        "/chat/completions",
        json={
            "model": config.slug,
            "messages": [{"role": "user", "content": "Create Jane"}],
            **extra,
        },
    )


def _stream(client, config, **extra) -> tuple[list[dict], list[str]]:
    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": config.slug,
            "messages": [{"role": "user", "content": "Create Jane"}],
            "stream": True,
            **extra,
        },
    ) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in lines
        if line != "data: [DONE]"
    ]
    return chunks, lines


# --- Non-streaming --------------------------------------------------------


def test_opted_in_response_returns_events_and_model_sees_full_result(
    client: TestClient, events_config, catalog, mcp_result, model
):
    response = _post(client, events_config, include=["events"])

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Created Jane."
    assert [event["id"] for event in body["extensions"]["events"]] == ["evt-1"]
    assert body["extensions"]["events"][0]["event_type"] == "person.created"
    # The model receives the complete normal result and never the metadata.
    assert [json.loads(value) for value in model.tool_returns] == [PERSON]
    assert "evt-1" not in model.tool_returns[0]


def test_response_without_include_is_unchanged(
    client: TestClient, events_config, catalog, mcp_result, model
):
    with patch("app.services.mcp.tool_executor.parse_mcp_metadata") as parse:
        response = _post(client, events_config)

    assert response.status_code == 200
    assert "extensions" not in response.json()
    assert set(response.json()) == {
        "id",
        "object",
        "created",
        "model",
        "choices",
        "usage",
    }
    parse.assert_not_called()


def test_nested_extra_body_include_is_honored(
    client: TestClient, events_config, catalog, mcp_result, model
):
    response = _post(client, events_config, extra_body={"include": ["events"]})

    assert [event["id"] for event in response.json()["extensions"]["events"]] == [
        "evt-1"
    ]


def test_requested_channel_without_events_returns_empty_array(
    client: TestClient, events_config, catalog, mcp_result, model
):
    mcp_result.return_value = CallToolResult(
        content=[], structured_content=PERSON, meta=None, data=PERSON, is_error=False
    )

    response = _post(client, events_config, include=["events"])

    assert response.json()["extensions"] == {"events": []}


def test_invalid_metadata_does_not_fail_the_completion(
    client: TestClient, events_config, catalog, mcp_result, model
):
    mcp_result.return_value = CallToolResult(
        content=[],
        structured_content=PERSON,
        meta=events_meta(event_payload(tags=["origin:http-api"])),
        data=PERSON,
        is_error=False,
    )

    response = _post(client, events_config, include=["events"])

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Created Jane."
    assert response.json()["extensions"] == {"events": []}


def test_events_on_closed_config_are_omitted_and_reported_in_header(
    client: TestClient, closed_config, catalog, mcp_result, model
):
    with patch("app.services.mcp.tool_executor.parse_mcp_metadata") as parse:
        response = _post(client, closed_config, include=["events"])

    # The completion still succeeds; the channel is omitted (not an empty
    # list, which would mean "no events happened") and named in a header.
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Created Jane."
    assert "extensions" not in response.json()
    assert response.headers["X-Modela-Omitted-Include"] == "events"
    parse.assert_not_called()


def test_omitted_include_header_absent_when_channel_is_delivered(
    client: TestClient, events_config, catalog, mcp_result, model
):
    response = _post(client, events_config, include=["events"])

    assert "X-Modela-Omitted-Include" not in response.headers


def test_unsupported_include_returns_422(client: TestClient, events_config):
    response = _post(client, events_config, include=["tool_executions"])

    assert response.status_code == 422


def test_expose_events_defaults_to_false(db: Session):
    config = ModelConfigRepository(db).create(
        {"slug": "default-closed", "name": "x", "provider": "openai", "model": "m"}
    )

    assert config.expose_events is False


def _sdk_timeout() -> ModelAPIError:
    """A provider timeout as pydantic-ai surfaces it from the OpenAI SDK."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    sdk_error = openai.APITimeoutError(request=request)
    sdk_error.__cause__ = httpx.ReadTimeout("timed out", request=request)
    error = ModelAPIError(model_name="gpt-4o", message="Request timed out.")
    error.__cause__ = sdk_error
    return error


# Every classified failure keeps the status and body it has without the
# `events` opt-in; opting in only adds the `extensions` member.
CLASSIFIED_FAILURES = [
    (UnexpectedModelBehavior("provider failed"), 502, "provider failed"),
    (_sdk_timeout(), 504, "Request timed out."),
    (
        ModelHTTPError(503, "gpt-4o", "overloaded"),
        502,
        "status_code: 503, model_name: gpt-4o, body: overloaded",
    ),
    (InvalidParameterError("bad temperature"), 422, "bad temperature"),
    (ResourceNotFoundError("knowledge base missing"), 404, "knowledge base missing"),
]


def _post_failing(client, config, error, **extra):
    with patch(
        "app.commands.completions.create_completion_command.build_model",
        return_value=FailAfterCreateModel(error),
    ):
        return _post(client, config, **extra)


def _truncate_after_one_event(mcp_result):
    mcp_result.return_value = CallToolResult(
        content=[],
        structured_content=PERSON,
        meta=events_meta(
            EVENT,
            event_payload("evt-2"),
            event_payload("evt-3"),
        ),
        data=PERSON,
        is_error=False,
    )
    return patch(
        "app.commands.completions.create_completion_command.CompletionEventCollector",
        return_value=CompletionEventCollector(max_events=1),
    )


@pytest.mark.parametrize("opted_in", [False, True], ids=["direct", "events"])
@pytest.mark.parametrize(("error", "expected_status", "detail"), CLASSIFIED_FAILURES)
def test_completion_failures_keep_status_and_body_with_events_opt_in(
    client: TestClient,
    events_config,
    catalog,
    mcp_result,
    error,
    expected_status,
    detail,
    opted_in,
):
    extra = {"include": ["events"]} if opted_in else {}
    response = _post_failing(client, events_config, error, **extra)

    body = response.json()
    extensions = body.pop("extensions", None)
    assert response.status_code == expected_status
    assert body == {"detail": detail}
    if opted_in:
        assert extensions["events"][0]["id"] == "evt-1"
    else:
        assert extensions is None


def test_unexpected_failure_after_commit_is_logged_with_events(
    client: TestClient, events_config, catalog, mcp_result
):
    # Patch the module logger directly: the app's logging config disables
    # propagation once the app is built, so caplog would miss it.
    with patch("app.exceptions.handlers.logger") as logger:
        response = _post_failing(
            client,
            events_config,
            RuntimeError("post-commit failure"),
            include=["events"],
        )

    body = response.json()
    assert response.status_code == 500
    assert body["code"] == 500
    assert "RuntimeError: post-commit failure" in body["message"]
    assert body["extensions"]["events"][0]["id"] == "evt-1"
    # A handled wrapper never reaches ServerErrorMiddleware, so the handler
    # must log the original error itself for it to reach error reporting.
    logger.error.assert_called_once()
    assert isinstance(logger.error.call_args.kwargs["exc_info"], RuntimeError)


def test_failure_response_without_event_opt_in_remains_unchanged(
    client: TestClient, events_config, catalog, mcp_result
):
    with patch(
        "app.commands.completions.create_completion_command.build_model",
        return_value=FailAfterCreateModel(UnexpectedModelBehavior("provider failed")),
    ):
        response = _post(client, events_config)

    assert response.status_code == 502
    assert "extensions" not in response.json()


def test_structured_output_failure_preserves_events_and_validation_details(
    client: TestClient, db: Session, catalog, mcp_result
):
    config = _config(
        db,
        "events-structured-failure",
        expose_events=True,
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )
    with patch(
        "app.commands.completions.create_completion_command.build_model",
        return_value=FailAfterCreateModel(
            UnexpectedModelBehavior("structured response was invalid")
        ),
    ):
        response = _post(client, config, include=["events"])

    body = response.json()
    assert response.status_code == 502
    assert body["validation_errors"] == [{"message": "structured response was invalid"}]
    assert body["raw_content"] == "structured response was invalid"
    assert body["extensions"]["events"][0]["id"] == "evt-1"
    assert "tool_executions" not in body["extensions"]


def test_non_streaming_response_reports_event_truncation(
    client: TestClient, events_config, catalog, mcp_result, model
):
    with _truncate_after_one_event(mcp_result):
        response = _post(client, events_config, include=["events"])

    assert response.status_code == 200
    assert [event["id"] for event in response.json()["extensions"]["events"]] == [
        "evt-1"
    ]
    assert response.json()["extensions"]["truncations"] == [
        {"channel": "events", "truncated": True, "dropped_count": 2}
    ]


def test_failure_response_reports_event_truncation_without_diagnostics(
    client: TestClient, events_config, catalog, mcp_result
):
    with _truncate_after_one_event(mcp_result):
        response = _post_failing(
            client,
            events_config,
            UnexpectedModelBehavior("provider failed"),
            include=["events"],
        )

    assert response.status_code == 502
    extensions = response.json()["extensions"]
    assert [event["id"] for event in extensions["events"]] == ["evt-1"]
    assert extensions["truncations"] == [
        {"channel": "events", "truncated": True, "dropped_count": 2}
    ]
    assert "tool_executions" not in extensions


# --- Streaming ------------------------------------------------------------


def test_stream_emits_event_chunk_between_text_in_execution_order(
    client: TestClient, events_config, catalog, mcp_result, model
):
    chunks, lines = _stream(client, events_config, include=["events"])

    event_chunks = [c for c in chunks if "extensions" in c]
    assert len(event_chunks) == 1
    event_chunk = event_chunks[0]
    assert event_chunk["object"] == "chat.completion.chunk"
    assert event_chunk["choices"] == []
    assert event_chunk["extensions"]["event"]["id"] == "evt-1"

    index = chunks.index(event_chunk)
    text = lambda part: "".join(
        c["choices"][0]["delta"].get("content") or "" for c in part if c["choices"]
    )
    assert text(chunks[:index]) == "Creating. "
    assert text(chunks[index + 1 :]) == "Created Jane."

    text_chunks = [c for c in chunks if c["choices"]]
    assert text_chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert all(c["id"] == chunks[0]["id"] for c in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert lines[-1] == "data: [DONE]"


def test_stream_without_include_has_no_event_chunks(
    client: TestClient, events_config, catalog, mcp_result, model
):
    chunks, _ = _stream(client, events_config)

    assert all("extensions" not in c for c in chunks)
    assert all(c["choices"] for c in chunks)


def test_stream_emits_one_truncation_marker_after_last_retained_event(
    client: TestClient, events_config, catalog, mcp_result, model
):
    with _truncate_after_one_event(mcp_result):
        chunks, lines = _stream(client, events_config, include=["events"])

    event_index = next(
        index
        for index, chunk in enumerate(chunks)
        if chunk.get("extensions", {}).get("event")
    )
    marker_indexes = [
        index
        for index, chunk in enumerate(chunks)
        if chunk.get("extensions", {}).get("truncation")
    ]
    assert len(marker_indexes) == 1
    assert event_index < marker_indexes[0] < len(chunks) - 1
    marker = chunks[marker_indexes[0]]
    assert marker["choices"] == []
    assert marker["extensions"]["truncation"] == {
        "channel": "events",
        "truncated": True,
        "dropped_count": 2,
    }
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert lines[-1] == "data: [DONE]"


def test_stream_events_on_closed_config_are_omitted_and_reported_in_header(
    client: TestClient, closed_config, catalog, mcp_result, model
):
    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": closed_config.slug,
            "messages": [{"role": "user", "content": "Create Jane"}],
            "stream": True,
            "include": ["events"],
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["X-Modela-Omitted-Include"] == "events"
        lines = [line for line in response.iter_lines() if line]

    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in lines
        if line != "data: [DONE]"
    ]
    assert all("extensions" not in c for c in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
