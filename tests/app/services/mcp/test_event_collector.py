from pydantic_core import to_json

from app.services.mcp.event_collector import CompletionEventCollector
from tests.app.services.mcp.event_fixtures import mcp_event


def test_records_serialized_events_in_order():
    collector = CompletionEventCollector()

    collector.record([mcp_event("a"), mcp_event("b")], tool_name="linden__create")
    collector.record([mcp_event("c")], tool_name="linden__update")

    assert [event["id"] for event in collector.events] == ["a", "b", "c"]
    # Serialized with the Tessera Event field names, JSON-ready.
    assert collector.events[0]["event_type"] == "person.created"
    assert collector.events[0]["time"].startswith("2026-10-06T10:00:00")
    assert collector.events[0]["tags"] == ["origin:mcp"]


def test_drain_returns_only_events_recorded_since_previous_drain():
    collector = CompletionEventCollector()
    collector.record([mcp_event("a")], tool_name="t")

    assert [event["id"] for event in collector.drain()] == ["a"]
    assert collector.drain() == []

    collector.record([mcp_event("b")], tool_name="t")
    assert [event["id"] for event in collector.drain()] == ["b"]
    assert [event["id"] for event in collector.events] == ["a", "b"]


def test_event_count_budget_suppresses_later_events():
    collector = CompletionEventCollector(max_events=2)

    collector.record([mcp_event("a"), mcp_event("b"), mcp_event("c")], tool_name="t")

    assert [event["id"] for event in collector.events] == ["a", "b"]
    assert collector.suppressed_count == 1
    assert collector.truncations == [
        {"channel": "events", "truncated": True, "dropped_count": 1}
    ]


def test_byte_budget_suppresses_events_that_do_not_fit():
    one_event_bytes = len(to_json(mcp_event("a").model_dump(mode="json")))
    # Room for exactly one event.
    collector = CompletionEventCollector(max_bytes=one_event_bytes)

    collector.record([mcp_event("a"), mcp_event("b")], tool_name="t")

    assert [event["id"] for event in collector.events] == ["a"]
    assert collector.suppressed_count == 1


def test_truncation_marker_is_drained_once_with_final_suppressed_count():
    collector = CompletionEventCollector(max_events=1)
    collector.record([mcp_event("a"), mcp_event("b")], tool_name="t")
    collector.record([mcp_event("c"), mcp_event("d")], tool_name="t")

    assert collector.drain_truncation() == {
        "channel": "events",
        "truncated": True,
        "dropped_count": 3,
    }
    assert collector.drain_truncation() is None


def test_collector_without_suppression_has_no_truncation_marker():
    collector = CompletionEventCollector()
    collector.record([mcp_event("a")], tool_name="t")

    assert collector.truncations == []
    assert collector.drain_truncation() is None
