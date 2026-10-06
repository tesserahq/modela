"""Benchmark the per-tool-call cost of the Chat Completions `events` channel.

Measures the work this feature adds to the LLM critical path for one MCP tool
result: parsing `_meta` with the SDK, recording events in the collector, and
serializing the agent value. No network, database, or model is involved.

Run in a quiet environment (not CI):

    ENV=test poetry run python scripts/benchmark_completion_events.py
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable

from tessera_sdk.mcp import MCP_EVENTS_META_KEY

from app.services.mcp.event_collector import CompletionEventCollector
from app.services.mcp.tool_executor import _parse_events

ITERATIONS = 2_000
AGENT_VALUE = {"id": "person-1", "first_name": "Jane", "email": "jane@example.com"}


def _event(index: int) -> dict:
    return {
        "id": f"evt-{index}",
        "source": "/linden/persons",
        "event_type": "person.created",
        "subject": f"/persons/person-{index}",
        "time": "2026-10-06T10:00:00Z",
        "tags": ["origin:mcp"],
        "event_data": {
            "resource": {"type": "person", "id": f"person-{index}"},
            "related": [{"type": "account", "id": "account-1"}],
            "changed_fields": ["first_name", "last_name"],
        },
    }


def _meta(count: int) -> dict:
    return {MCP_EVENTS_META_KEY: [_event(i) for i in range(count)]}


def _opted_out(meta: dict) -> Callable[[], None]:
    # Opted-out callers skip parsing entirely; only the agent value is built.
    def run() -> None:
        json.dumps(AGENT_VALUE, default=str)

    return run


def _opted_in(meta: dict) -> Callable[[], None]:
    def run() -> None:
        events = _parse_events(meta, "linden", "create_person")
        CompletionEventCollector().record(events, tool_name="linden__create_person")
        json.dumps(AGENT_VALUE, default=str)

    return run


def _measure(fn: Callable[[], None]) -> tuple[float, float]:
    for _ in range(100):  # warm up
        fn()
    samples = []
    for _ in range(ITERATIONS):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1_000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95)]


def main() -> None:
    cases = [
        ("opted out, 1 event in _meta", _opted_out(_meta(1))),
        ("opted in, no _meta", _opted_in({})),
        ("opted in, 1 event", _opted_in(_meta(1))),
        ("opted in, 10 events", _opted_in(_meta(10))),
        ("opted in, 100 events (count limit)", _opted_in(_meta(100))),
    ]
    print(f"{'case':<38}{'p50 µs':>10}{'p95 µs':>10}")
    for name, fn in cases:
        p50, p95 = _measure(fn)
        print(f"{name:<38}{p50:>10.1f}{p95:>10.1f}")


if __name__ == "__main__":
    main()
