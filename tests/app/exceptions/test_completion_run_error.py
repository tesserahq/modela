from app.exceptions.completion_run_error import CompletionRunError
from app.exceptions.provider_errors import ProviderError


def test_completion_run_error_preserves_original_error_and_isolates_events():
    source = [{"id": "evt-1", "event_data": {"resource": {"id": "person-1"}}}]
    original = ProviderError("later model round failed")

    error = CompletionRunError(original, events=source)
    source[0]["event_data"]["resource"]["id"] = "mutated"

    assert error.original_error is original
    assert error.events == [
        {"id": "evt-1", "event_data": {"resource": {"id": "person-1"}}}
    ]
