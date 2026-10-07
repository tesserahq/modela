"""Typed failure for a completion that already produced durable effects."""

from app.services.completions.run_context import CompletionEventSnapshot


class CompletionRunError(Exception):
    """Preserve an inference error and its committed domain-event snapshot."""

    def __init__(
        self,
        original_error: Exception,
        *,
        event_snapshot: CompletionEventSnapshot,
    ) -> None:
        super().__init__(str(original_error))
        self.original_error = original_error
        self.event_snapshot = event_snapshot

    @property
    def events(self) -> list[dict]:
        return self.event_snapshot.events
