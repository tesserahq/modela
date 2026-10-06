import pytest
from pydantic import ValidationError
from tessera_sdk.mcp import CompletionInclude

from app.schemas.completion import CompletionCreate

MESSAGES = [{"role": "user", "content": "Hi"}]


def test_include_is_optional_and_events_are_off_by_default():
    payload = CompletionCreate(messages=MESSAGES)

    assert payload.include is None
    assert payload.wants_events is False


def test_top_level_include_requests_events():
    payload = CompletionCreate(messages=MESSAGES, include=["events"])

    assert payload.include == [CompletionInclude.EVENTS]
    assert payload.wants_events is True


def test_empty_include_requests_nothing():
    assert CompletionCreate(messages=MESSAGES, include=[]).wants_events is False


def test_nested_extra_body_include_is_an_alias():
    # tessera-sdk ModelaClient sends extra_body as a literal nested key.
    payload = CompletionCreate(messages=MESSAGES, extra_body={"include": ["events"]})

    assert payload.include == [CompletionInclude.EVENTS]
    assert payload.wants_events is True


def test_matching_top_level_and_nested_include_are_merged():
    payload = CompletionCreate(
        messages=MESSAGES,
        include=["events", "events"],
        extra_body={"include": ["events"]},
    )

    assert payload.wants_events is True


def test_conflicting_include_sources_are_rejected():
    with pytest.raises(ValidationError, match="conflicts"):
        CompletionCreate(
            messages=MESSAGES,
            include=["events"],
            extra_body={"include": []},
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"include": ["not-a-channel"]},
        {"extra_body": {"include": ["not-a-channel"]}},
        {"extra_body": {"include": "events"}},
    ],
)
def test_invalid_include_values_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        CompletionCreate(messages=MESSAGES, **kwargs)


def test_tool_executions_is_not_supported_yet():
    with pytest.raises(ValidationError, match="tool_executions"):
        CompletionCreate(messages=MESSAGES, include=["tool_executions"])


def test_other_extra_body_content_is_still_ignored():
    payload = CompletionCreate(messages=MESSAGES, extra_body={"temperature": 0.2})

    assert payload.include is None
