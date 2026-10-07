"""Typed failure for a completion that already produced durable effects."""

from copy import deepcopy


class CompletionRunError(Exception):
    """Preserve an inference error and bounded event-channel state."""

    def __init__(
        self,
        original_error: Exception,
        *,
        events: list[dict],
        truncations: list[dict] | None = None,
    ) -> None:
        super().__init__(str(original_error))
        self.original_error = original_error
        self.events = deepcopy(events)
        self.truncations = deepcopy(truncations or [])
