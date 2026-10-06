from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.client.client import CallToolResult

from app.services.mcp.tool_executor import MCPToolExecutor
from tests.app.services.mcp.event_fixtures import event_payload, events_meta

PERSON = {"id": "person-1", "email": "jane@example.com", "phone": "555-0100"}


def _result(*, data=PERSON, meta=None, is_error=False) -> CallToolResult:
    return CallToolResult(
        content=[],
        structured_content=data if isinstance(data, dict) else None,
        meta=meta,
        data=data,
        is_error=is_error,
    )


@pytest.fixture
def mcp_call():
    """Patch server lookup, credentials and transport; yield the call_tool mock."""
    client = MagicMock()
    client.call_tool = AsyncMock()

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


async def _execute(parse_metadata: bool):
    return await MCPToolExecutor(MagicMock()).execute_with_metadata(
        server_id="linden",
        original_name="create_person",
        args={"first_name": "Jane"},
        parse_metadata=parse_metadata,
    )


@pytest.mark.asyncio
async def test_metadata_bearing_result_returns_events_and_unchanged_agent_value(
    mcp_call,
):
    mcp_call.return_value = _result(meta=events_meta(event_payload("evt-1")))

    result = await _execute(parse_metadata=True)

    # The model still receives the complete normal result, PII included.
    assert result.agent_value == PERSON
    assert [event.id for event in result.events] == ["evt-1"]


@pytest.mark.asyncio
async def test_opted_out_caller_never_parses_metadata(mcp_call):
    mcp_call.return_value = _result(meta=events_meta(event_payload()))

    with patch("app.services.mcp.tool_executor.parse_mcp_metadata") as parse:
        result = await _execute(parse_metadata=False)

    parse.assert_not_called()
    assert result.agent_value == PERSON
    assert result.events == ()


@pytest.mark.asyncio
async def test_legacy_result_without_meta_is_unchanged(mcp_call):
    mcp_call.return_value = _result(meta=None)

    result = await _execute(parse_metadata=True)

    assert result.agent_value == PERSON
    assert result.events == ()


@pytest.mark.asyncio
async def test_failed_tool_contributes_no_events(mcp_call):
    mcp_call.return_value = _result(
        data="boom", meta=events_meta(event_payload()), is_error=True
    )

    result = await _execute(parse_metadata=True)

    assert result.agent_value["error"] == "Tool execution failed"
    assert result.events == ()


@pytest.mark.asyncio
async def test_unknown_domain_event_type_is_accepted(mcp_call):
    mcp_call.return_value = _result(
        meta=events_meta(event_payload(event_type="household.archived"))
    )

    result = await _execute(parse_metadata=True)

    assert [event.event_type for event in result.events] == ["household.archived"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "meta",
    [
        events_meta(event_payload(tags=["origin:http-api"])),
        events_meta(event_payload(), {"source": "/x", "event_type": "y"}),
        {"events": [event_payload()]},
        events_meta(*[event_payload(f"evt-{i}") for i in range(101)]),
    ],
    ids=["wrong-origin", "missing-identity", "unnamespaced", "over-count"],
)
async def test_invalid_metadata_is_dropped_and_logged_without_values(mcp_call, meta):
    mcp_call.return_value = _result(meta=meta)

    # Patch the module logger directly: the app's logging config disables
    # propagation once the app is built, so caplog would miss it in a full run.
    with patch("app.services.mcp.tool_executor.logger") as logger:
        result = await _execute(parse_metadata=True)

    assert result.agent_value == PERSON
    assert result.events == ()
    logger.warning.assert_called_once()
    fmt, *args = logger.warning.call_args.args
    logged = fmt % tuple(args)
    assert "create_person" in logged
    assert "person-1" not in logged
    assert "/linden/persons" not in logged


@pytest.mark.asyncio
async def test_execute_still_returns_only_the_agent_value(mcp_call):
    mcp_call.return_value = _result(meta=events_meta(event_payload()))

    value = await MCPToolExecutor(MagicMock()).execute(
        server_id="linden", original_name="create_person", args={}
    )

    assert value == PERSON
