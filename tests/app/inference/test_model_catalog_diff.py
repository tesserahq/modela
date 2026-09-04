from datetime import UTC, datetime

from app.inference.model_catalog_diff import diff_provider_models
from app.schemas.provider import LiveProviderModel


def _live(id: str, created_at: str) -> LiveProviderModel:
    return LiveProviderModel(
        id=id, created_at=datetime.fromisoformat(created_at).replace(tzinfo=UTC)
    )


def test_no_drift_when_live_matches_curated():
    curated = {"claude-opus-5", "claude-sonnet-5"}
    live = [
        _live("claude-opus-5", "2026-01-01T00:00:00"),
        _live("claude-sonnet-5", "2026-01-01T00:00:00"),
    ]

    diff = diff_provider_models(curated, live, ("claude",))

    assert diff.added == []
    assert diff.removed == []
    assert diff.newer_model_id is None


def test_detects_pure_addition():
    curated = {"claude-opus-5"}
    live = [
        _live("claude-opus-5", "2026-01-01T00:00:00"),
        _live("claude-opus-6", "2026-06-01T00:00:00"),
    ]

    diff = diff_provider_models(curated, live, ("claude",))

    assert diff.added == ["claude-opus-6"]
    assert diff.removed == []
    assert diff.newer_model_id == "claude-opus-6"


def test_detects_pure_removal():
    curated = {"claude-opus-5", "claude-opus-4"}
    live = [_live("claude-opus-5", "2026-01-01T00:00:00")]

    diff = diff_provider_models(curated, live, ("claude",))

    assert diff.added == []
    assert diff.removed == ["claude-opus-4"]
    assert diff.newer_model_id is None


def test_detects_addition_and_removal_together():
    curated = {"claude-opus-5", "claude-opus-4"}
    live = [
        _live("claude-opus-5", "2026-01-01T00:00:00"),
        _live("claude-opus-6", "2026-06-01T00:00:00"),
    ]

    diff = diff_provider_models(curated, live, ("claude",))

    assert diff.added == ["claude-opus-6"]
    assert diff.removed == ["claude-opus-4"]
    assert diff.newer_model_id == "claude-opus-6"


def test_ignores_live_ids_outside_family_prefixes():
    curated = {"gpt-4o"}
    live = [
        _live("gpt-4o", "2026-01-01T00:00:00"),
        _live("text-embedding-3-large", "2026-06-01T00:00:00"),
        _live("whisper-1", "2026-06-01T00:00:00"),
    ]

    diff = diff_provider_models(curated, live, ("gpt", "o"))

    assert diff.added == []
    assert diff.removed == []
    assert diff.newer_model_id is None


def test_no_newer_model_when_curated_id_is_still_the_newest_live_entry():
    curated = {"claude-opus-5", "claude-opus-4"}
    live = [
        _live("claude-opus-5", "2026-06-01T00:00:00"),
        _live("claude-opus-4", "2026-01-01T00:00:00"),
    ]

    diff = diff_provider_models(curated, live, ("claude",))

    assert diff.newer_model_id is None


def test_empty_live_list_reports_all_curated_ids_as_removed():
    curated = {"claude-opus-5"}

    diff = diff_provider_models(curated, [], ("claude",))

    assert diff.added == []
    assert diff.removed == ["claude-opus-5"]
    assert diff.newer_model_id is None
