"""Shared Tessera MCP event fixtures for completion-event tests."""

from tessera_sdk.mcp import MCP_EVENTS_META_KEY, MCPEvent


def event_payload(event_id: str = "evt-1", **overrides) -> dict:
    return {
        "id": event_id,
        "source": "/linden/persons",
        "event_type": "person.created",
        "subject": "/persons/person-1",
        "time": "2026-10-06T10:00:00Z",
        "tags": ["origin:mcp"],
        "event_data": {
            "resource": {"type": "person", "id": "person-1"},
            "related": [{"type": "account", "id": "account-1"}],
        },
        **overrides,
    }


def events_meta(*payloads: dict) -> dict:
    return {MCP_EVENTS_META_KEY: list(payloads)}


def mcp_event(event_id: str = "evt-1", **overrides) -> MCPEvent:
    return MCPEvent(**event_payload(event_id, **overrides))
