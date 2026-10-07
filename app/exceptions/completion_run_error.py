"""Typed failure for a completion that already produced durable effects."""

from copy import deepcopy


class CompletionRunError(Exception):
    """Preserve an inference error and the domain events committed before it."""

    def __init__(self, original_error: Exception, *, events: list[dict]) -> None:
        super().__init__(str(original_error))
        self.original_error = original_error
        self.events = deepcopy(events)
