from app.exceptions.completion_run_error import CompletionRunError
from app.exceptions.provider_errors import ProviderError
from app.services.completions.run_context import CompletionEventSnapshot


def test_completion_run_error_preserves_original_error_and_immutable_events():
    source = [{"id": "evt-1", "event_data": {"resource": {"id": "person-1"}}}]
    snapshot = CompletionEventSnapshot.capture(source)
    original = ProviderError("later model round failed")

    error = CompletionRunError(original, event_snapshot=snapshot)
    source[0]["id"] = "mutated"
    first_read = error.events
    first_read[0]["id"] = "also-mutated"

    assert error.original_error is original
    assert error.events[0]["id"] == "evt-1"
