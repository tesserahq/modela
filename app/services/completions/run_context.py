"""State that survives one completion run, independent of HTTP request state."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.mcp.event_collector import CompletionEventCollector


@dataclass(frozen=True)
class CompletionEventSnapshot:
    """Immutable serialized copy of events committed during a completion."""

    _events: tuple[bytes, ...]

    @classmethod
    def capture(cls, events: list[dict]) -> CompletionEventSnapshot:
        return cls(
            tuple(
                json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
                for event in events
            )
        )

    @property
    def events(self) -> list[dict]:
        """Return fresh values so callers cannot mutate the stored snapshot."""
        return [json.loads(event) for event in self._events]


@dataclass(frozen=True)
class CompletionRunContext:
    """Completion-owned extension state shared across delivery adapters."""

    event_collector: CompletionEventCollector | None = None

    def snapshot_events(self) -> CompletionEventSnapshot:
        events = self.event_collector.events if self.event_collector else []
        return CompletionEventSnapshot.capture(events)
