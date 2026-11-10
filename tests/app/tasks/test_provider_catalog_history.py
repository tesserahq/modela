from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.provider_model_catalog import (
    ProviderModelCatalogEntry,
    ProviderModelCatalogSnapshot,
)
from app.schemas.provider import ProviderModelSchema
from app.services.provider_catalog_history import (
    ERROR_HTTP,
    ERROR_MISSING_KEY,
    ERROR_NETWORK,
    ERROR_UNKNOWN,
    categorize_fetch_error,
)
from app.tasks.check_provider_model_catalog import check_provider_model_catalog_task
from tests.app.tasks.test_check_provider_model_catalog import _FakeAdapter, _live


@pytest.fixture(autouse=True)
def _task_sessions_use_test_db(short_sessions):
    with patch("app.tasks.check_provider_model_catalog.session_scope", short_sessions):
        yield


def _run(adapter, publisher=None):
    publisher = publisher or MagicMock()
    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {adapter.provider_id: adapter},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=publisher,
        ),
    ):
        check_provider_model_catalog_task()
    return publisher


def _entries(db, provider_id="anthropic"):
    return (
        db.query(ProviderModelCatalogEntry)
        .filter(ProviderModelCatalogEntry.provider_id == provider_id)
        .order_by(ProviderModelCatalogEntry.kind, ProviderModelCatalogEntry.model_id)
        .all()
    )


def _snapshot(db, provider_id="anthropic"):
    return db.get(ProviderModelCatalogSnapshot, provider_id)


def _curated_adapter(live, curated=None, fetch_error=None):
    curated = curated or [
        ProviderModelSchema(id="claude-opus-5", name="Claude Opus 5"),
        ProviderModelSchema(id="claude-opus-4", name="Claude Opus 4"),
    ]
    return _FakeAdapter(
        "anthropic", ("claude",), curated=curated, live=live, fetch_error=fetch_error
    )


def test_first_run_records_drift_against_curated_list_and_stores_snapshot(db):
    adapter = _curated_adapter(live=[_live("claude-opus-5"), _live("claude-opus-6")])

    _run(adapter)

    rows = {(e.kind, e.model_id) for e in _entries(db)}
    assert rows == {("added", "claude-opus-6"), ("removed", "claude-opus-4")}
    assert _snapshot(db).model_ids == ["claude-opus-5", "claude-opus-6"]


def test_unchanged_drift_is_recorded_once_and_not_published_again(db):
    adapter = _curated_adapter(live=[_live("claude-opus-5"), _live("claude-opus-6")])
    first = _run(adapter)
    second = _run(adapter)

    assert len(_entries(db)) == 2
    assert first.publish_sync.call_count == 2
    assert second.publish_sync.call_count == 0


def test_failed_fetch_records_check_failed_and_keeps_snapshot(db):
    healthy = _curated_adapter(live=[_live("claude-opus-5")])
    _run(healthy)
    before = list(_snapshot(db).model_ids)

    broken = _curated_adapter(
        live=[],
        fetch_error=ValueError("ANTHROPIC_API_KEY is not configured"),
    )
    publisher = _run(broken)

    failed = [e for e in _entries(db) if e.kind == "check_failed"]
    assert len(failed) == 1
    assert failed[0].error_category == ERROR_MISSING_KEY
    assert failed[0].model_id is None
    assert _snapshot(db).model_ids == before
    assert publisher.publish_sync.call_count == 0


def test_model_added_while_check_was_failing_is_recorded_once_on_recovery(db):
    _run(_curated_adapter(live=[_live("claude-opus-5")]))

    _run(
        _curated_adapter(
            live=[],
            fetch_error=httpx.ConnectError("boom"),
        )
    )
    _run(_curated_adapter(live=[_live("claude-opus-5"), _live("claude-opus-7")]))
    _run(_curated_adapter(live=[_live("claude-opus-5"), _live("claude-opus-7")]))

    added = [e for e in _entries(db) if e.kind == "added"]
    assert [e.model_id for e in added] == ["claude-opus-7"]
    assert len([e for e in _entries(db) if e.kind == "check_failed"]) == 1


def test_failure_of_one_provider_does_not_stop_the_snapshot_of_another(db):
    healthy = _FakeAdapter(
        "openai",
        ("gpt",),
        curated=[ProviderModelSchema(id="gpt-4o", name="GPT-4o")],
        live=[_live("gpt-4o")],
    )
    broken = _FakeAdapter(
        "anthropic",
        ("claude",),
        curated=[],
        live=[],
        fetch_error=RuntimeError("unexpected"),
    )
    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {"anthropic": broken, "openai": healthy},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=MagicMock(),
        ),
    ):
        check_provider_model_catalog_task()

    assert _snapshot(db, "openai").model_ids == ["gpt-4o"]
    assert [e.kind for e in _entries(db, "anthropic")] == ["check_failed"]
    assert _entries(db, "anthropic")[0].error_category == ERROR_UNKNOWN


@pytest.mark.parametrize(
    "exc, category",
    [
        (ValueError("OPENAI_API_KEY is not configured"), ERROR_MISSING_KEY),
        (httpx.ConnectError("refused"), ERROR_NETWORK),
        (httpx.ReadTimeout("slow"), ERROR_NETWORK),
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(401),
            ),
            ERROR_HTTP,
        ),
        (RuntimeError("anything else"), ERROR_UNKNOWN),
    ],
)
def test_fetch_errors_map_to_categories(exc, category):
    assert categorize_fetch_error(exc) == category
