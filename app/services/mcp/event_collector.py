"""Request-scoped collector for MCP domain events exposed through completions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic_core import to_json
from tessera_sdk.mcp import MCPEvent

from app.infra.logging_config import get_logger

logger = get_logger(__name__)

# PRD 0022 per-response budget for the `events` channel. These bound what one
# completion returns; they never stop or delay tool execution.
DEFAULT_MAX_EVENTS = 100
DEFAULT_MAX_EVENT_BYTES = 256 * 1024


class CompletionEventCollector:
    """Ordered, bounded store of validated events for one completion request.

    Each event is serialized exactly once when recorded; streaming callers drain
    newly recorded events and non-streaming callers read the full list. Once a
    budget is exhausted, later events are suppressed and not retained.
    """

    def __init__(
        self,
        *,
        max_events: int = DEFAULT_MAX_EVENTS,
        max_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    ) -> None:
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._events: list[dict[str, Any]] = []
        self._bytes = 0
        self._drained = 0
        self._suppressed = 0

    def record(self, events: Iterable[MCPEvent], *, tool_name: str) -> None:
        for event in events:
            payload = event.model_dump(mode="json")
            # Byte budget is measured on the compact JSON form, using pydantic's
            # native serializer to keep this off the slower json module path.
            size = len(to_json(payload))
            if (
                len(self._events) >= self._max_events
                or self._bytes + size > self._max_bytes
            ):
                if self._suppressed == 0:
                    logger.warning(
                        "Completion event budget exhausted; suppressing further "
                        "events (first suppressed from tool %s)",
                        tool_name,
                    )
                self._suppressed += 1
                continue
            self._events.append(payload)
            self._bytes += size

    def drain(self) -> list[dict[str, Any]]:
        """Return events recorded since the previous drain, in order."""
        pending = self._events[self._drained :]
        self._drained = len(self._events)
        return pending

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @property
    def suppressed_count(self) -> int:
        return self._suppressed
