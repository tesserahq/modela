import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.mcp_tool import MCPCatalogTool
from app.services.mcp.event_collector import CompletionEventCollector
from app.services.mcp.mcp_toolset import MCPToolset
from app.services.mcp.tool_executor import MCPToolCallResult
from tests.app.services.mcp.event_fixtures import mcp_event

TOOL = MCPCatalogTool(
    qualified_name="linden__create_person",
    original_name="create_person",
    server_id="linden",
)
PERSON = {"id": "person-1", "email": "jane@example.com"}


def _executor(events=()):
    executor = MagicMock()
    executor.execute_with_metadata = AsyncMock(
        return_value=MCPToolCallResult(PERSON, tuple(events))
    )
    return executor


async def _call(toolset):
    return await toolset.call_tool(TOOL.qualified_name, {}, MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_records_events_and_returns_only_the_normal_result():
    collector = CompletionEventCollector()
    executor = _executor([mcp_event("evt-1")])
    toolset = MCPToolset([TOOL], executor, event_collector=collector)

    value = await _call(toolset)

    assert json.loads(value) == PERSON
    assert "evt-1" not in value
    assert [event["id"] for event in collector.events] == ["evt-1"]
    assert executor.execute_with_metadata.await_args.kwargs["parse_metadata"] is True


@pytest.mark.asyncio
async def test_without_collector_metadata_is_not_requested():
    executor = _executor()
    toolset = MCPToolset([TOOL], executor)

    value = await _call(toolset)

    assert json.loads(value) == PERSON
    assert executor.execute_with_metadata.await_args.kwargs["parse_metadata"] is False
