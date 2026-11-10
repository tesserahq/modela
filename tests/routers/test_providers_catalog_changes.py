from datetime import UTC, datetime
from uuid import uuid4

from app.models.provider_model_catalog import ProviderModelCatalogEntry


def _seed(db, **overrides):
    entry = ProviderModelCatalogEntry(
        provider_id=overrides.pop("provider_id", "openai"),
        kind=overrides.pop("kind", "removed"),
        model_id=overrides.pop("model_id", "o4-mini"),
        error_category=overrides.pop("error_category", None),
        detected_at=overrides.pop("detected_at", datetime(2026, 11, 10, tzinfo=UTC)),
        reviewed_at=overrides.pop("reviewed_at", None),
        reviewed_by_id=overrides.pop("reviewed_by_id", None),
    )
    db.add(entry)
    db.flush()
    return entry


def test_list_catalog_changes_returns_seeded_entries(client, db):
    _seed(db, model_id="o4-mini")
    _seed(db, model_id="gpt-4.1-nano")

    response = client.get("/providers/catalog-changes")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["model_id"] for item in body["items"]} == {"o4-mini", "gpt-4.1-nano"}


def test_list_catalog_changes_filters_by_provider_kind_and_review_state(
    client, db, setup_user
):
    _seed(db, provider_id="openai", kind="removed", model_id="o4-mini")
    _seed(
        db,
        provider_id="openai",
        kind="check_failed",
        model_id=None,
        error_category="missing_key",
    )
    _seed(db, provider_id="anthropic", kind="added", model_id="claude-opus-6")
    _seed(
        db,
        provider_id="openai",
        kind="removed",
        model_id="gpt-4.1-nano",
        reviewed_at=datetime(2026, 11, 11, tzinfo=UTC),
        reviewed_by_id=setup_user.id,
    )

    by_provider = client.get("/providers/catalog-changes?provider_id=anthropic").json()
    assert [i["model_id"] for i in by_provider["items"]] == ["claude-opus-6"]

    failures = client.get("/providers/catalog-changes?kind=check_failed").json()
    assert [i["error_category"] for i in failures["items"]] == ["missing_key"]

    unreviewed = client.get("/providers/catalog-changes?reviewed=false").json()
    assert unreviewed["total"] == 3
    assert all(i["reviewed_at"] is None for i in unreviewed["items"])

    reviewed = client.get("/providers/catalog-changes?reviewed=true").json()
    assert [i["model_id"] for i in reviewed["items"]] == ["gpt-4.1-nano"]


def test_mark_reviewed_records_the_signed_in_user(client, db, setup_user):
    entry = _seed(db, model_id="o4-mini")

    response = client.patch(
        f"/providers/catalog-changes/{entry.id}", json={"reviewed": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reviewed_at"] is not None
    assert body["reviewed_by_id"] == str(setup_user.id)


def test_clearing_review_removes_reviewer_and_time(client, db, setup_user):
    entry = _seed(
        db,
        model_id="o4-mini",
        reviewed_at=datetime(2026, 11, 11, tzinfo=UTC),
        reviewed_by_id=setup_user.id,
    )

    response = client.patch(
        f"/providers/catalog-changes/{entry.id}", json={"reviewed": False}
    )

    assert response.status_code == 200
    assert response.json()["reviewed_at"] is None
    assert response.json()["reviewed_by_id"] is None


def test_review_unknown_entry_returns_404(client):
    response = client.patch(
        f"/providers/catalog-changes/{uuid4()}", json={"reviewed": True}
    )

    assert response.status_code == 404
