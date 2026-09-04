from app.events.provider_model_events import (
    PROVIDER_MODEL_ADDED,
    PROVIDER_MODEL_REMOVED,
    build_provider_model_added_event,
    build_provider_model_removed_event,
)
from app.inference.model_catalog_diff import ModelCatalogDiff


def test_added_event_contains_provider_and_model_ids():
    diff = ModelCatalogDiff(
        added=["claude-opus-6"], removed=[], newer_model_id="claude-opus-6"
    )

    event = build_provider_model_added_event("anthropic", diff)

    assert event.event_type.endswith(PROVIDER_MODEL_ADDED)
    assert event.event_data["provider_id"] == "anthropic"
    assert event.event_data["model_ids"] == ["claude-opus-6"]
    assert event.event_data["newer_model_id"] == "claude-opus-6"
    assert event.subject == "/providers/anthropic/models"


def test_added_event_omits_newer_model_id_when_not_set():
    diff = ModelCatalogDiff(added=["gpt-4.5-mini"], removed=[], newer_model_id=None)

    event = build_provider_model_added_event("openai", diff)

    assert "newer_model_id" not in event.event_data


def test_removed_event_contains_provider_and_model_ids():
    diff = ModelCatalogDiff(added=[], removed=["claude-opus-4"], newer_model_id=None)

    event = build_provider_model_removed_event("anthropic", diff)

    assert event.event_type.endswith(PROVIDER_MODEL_REMOVED)
    assert event.event_data["provider_id"] == "anthropic"
    assert event.event_data["model_ids"] == ["claude-opus-4"]
    assert event.subject == "/providers/anthropic/models"
