"""Request-scoped collector for MCP domain events exposed through completions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic_core import to_json
from tessera_sdk.mcp import (
    CompletionInclude,
    MCPEvent,
    TruncationMarker,
)

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
        self._truncation_drained = False

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

    def drain_truncation(self) -> dict[str, Any] | None:
        """Return the final channel marker once, after event production ends.

        Callers wait until terminal success or failure so ``dropped_count`` is
        complete. A streaming transport can then place the marker after the
        last retained event without retaining any suppressed event payloads.
        """
        if self._truncation_drained or self._suppressed == 0:
            return None
        self._truncation_drained = True
        return self._truncation()

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @property
    def truncations(self) -> list[dict[str, Any]]:
        """Return the channel marker collection used by non-streaming output."""
        return [self._truncation()] if self._suppressed else []

    @property
    def suppressed_count(self) -> int:
        return self._suppressed

    def _truncation(self) -> dict[str, Any]:
        return TruncationMarker(
            channel=CompletionInclude.EVENTS,
            dropped_count=self._suppressed,
        ).model_dump(mode="json")
