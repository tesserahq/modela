from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.repositories.user_repository import UserRepository
from app.schemas.completion_request import CompletionRequestCreate


def _req(**overrides):
    base = dict(
        request_id=str(uuid4()),
        project_id="proj-a",
        provider="openai",
        model="gpt-4o",
        input_tokens=10,
        output_tokens=5,
        latency_ms=100,
        cost_estimate_usd=Decimal("1.00"),
        finish_reason="stop",
    )
    base.update(overrides)
    return CompletionRequestCreate(**base)


def _create(db: Session, **overrides):
    return CompletionRequestRepository(db).create(_req(**overrides))


def _make_user(db: Session) -> User:
    user = User(
        email=f"{uuid4()}@test.com",
        first_name="Test",
        last_name="User",
        provider="google",
        external_id=str(uuid4()),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# group_by=provider
# ---------------------------------------------------------------------------


def test_costs_group_by_provider(client: TestClient, db: Session):
    _create(db, provider="openai", cost_estimate_usd=Decimal("2.00"))
    _create(db, provider="openai", cost_estimate_usd=Decimal("3.00"))
    _create(db, provider="anthropic", cost_estimate_usd=Decimal("1.00"))

    resp = client.get("/analytics/costs", params={"group_by": "provider"})

    assert resp.status_code == 200
    data = resp.json()
    by_provider = {row["group_value"]: Decimal(row["total_cost_usd"]) for row in data}
    assert by_provider["openai"] == Decimal("5.00")
    assert by_provider["anthropic"] == Decimal("1.00")


def test_costs_group_by_provider_sorted_desc(client: TestClient, db: Session):
    _create(db, provider="anthropic", cost_estimate_usd=Decimal("0.50"))
    _create(db, provider="openai", cost_estimate_usd=Decimal("9.00"))

    resp = client.get("/analytics/costs", params={"group_by": "provider"})

    assert resp.status_code == 200
    totals = [Decimal(row["total_cost_usd"]) for row in resp.json()]
    assert totals == sorted(totals, reverse=True)


# ---------------------------------------------------------------------------
# group_by=model
# ---------------------------------------------------------------------------


def test_costs_group_by_model(client: TestClient, db: Session):
    _create(db, model="gpt-4o", cost_estimate_usd=Decimal("4.00"))
    _create(db, model="gpt-4o", cost_estimate_usd=Decimal("1.00"))
    _create(db, model="claude-3-5-sonnet", cost_estimate_usd=Decimal("2.00"))

    resp = client.get("/analytics/costs", params={"group_by": "model"})

    assert resp.status_code == 200
    by_model = {
        row["group_value"]: Decimal(row["total_cost_usd"]) for row in resp.json()
    }
    assert by_model["gpt-4o"] == Decimal("5.00")
    assert by_model["claude-3-5-sonnet"] == Decimal("2.00")


# ---------------------------------------------------------------------------
# group_by=project_id
# ---------------------------------------------------------------------------


def test_costs_group_by_project_id(client: TestClient, db: Session):
    _create(db, project_id="proj-x", cost_estimate_usd=Decimal("3.00"))
    _create(db, project_id="proj-y", cost_estimate_usd=Decimal("1.00"))

    resp = client.get("/analytics/costs", params={"group_by": "project_id"})

    assert resp.status_code == 200
    by_proj = {
        row["group_value"]: Decimal(row["total_cost_usd"]) for row in resp.json()
    }
    assert by_proj["proj-x"] == Decimal("3.00")
    assert by_proj["proj-y"] == Decimal("1.00")


# ---------------------------------------------------------------------------
# group_by=user (including null bucket)
# ---------------------------------------------------------------------------


def test_costs_group_by_user(client: TestClient, db: Session):
    user_a = _make_user(db)
    user_b = _make_user(db)
    _create(db, created_by_id=user_a.id, cost_estimate_usd=Decimal("5.00"))
    _create(db, created_by_id=user_a.id, cost_estimate_usd=Decimal("2.00"))
    _create(db, created_by_id=user_b.id, cost_estimate_usd=Decimal("1.00"))
    _create(db, created_by_id=None, cost_estimate_usd=Decimal("0.50"))

    resp = client.get("/analytics/costs", params={"group_by": "user"})

    assert resp.status_code == 200
    rows = resp.json()
    by_user = {
        str(row["group_value"]) if row["group_value"] else None: Decimal(
            row["total_cost_usd"]
        )
        for row in rows
    }
    assert by_user[str(user_a.id)] == Decimal("7.00")
    assert by_user[str(user_b.id)] == Decimal("1.00")
    assert by_user[None] == Decimal("0.50")


def test_costs_group_by_user_includes_group_details(client: TestClient, db: Session):
    user_a = _make_user(db)
    user_b = _make_user(db)
    _create(db, created_by_id=user_a.id, cost_estimate_usd=Decimal("5.00"))
    _create(db, created_by_id=user_b.id, cost_estimate_usd=Decimal("1.00"))

    resp = client.get("/analytics/costs", params={"group_by": "user"})

    assert resp.status_code == 200
    by_user = {row["group_value"]: row for row in resp.json()}

    details_a = by_user[str(user_a.id)]["group_details"]
    assert details_a == {
        "id": str(user_a.id),
        "first_name": user_a.first_name,
        "last_name": user_a.last_name,
        "email": user_a.email,
    }

    details_b = by_user[str(user_b.id)]["group_details"]
    assert details_b == {
        "id": str(user_b.id),
        "first_name": user_b.first_name,
        "last_name": user_b.last_name,
        "email": user_b.email,
    }


def test_costs_group_by_user_null_bucket_has_null_group_details(
    client: TestClient, db: Session
):
    _create(db, created_by_id=None, cost_estimate_usd=Decimal("0.50"))

    resp = client.get("/analytics/costs", params={"group_by": "user"})

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["group_value"] is None
    assert rows[0]["group_details"] is None


def test_costs_group_by_provider_has_null_group_details(
    client: TestClient, db: Session
):
    _create(db, provider="openai", cost_estimate_usd=Decimal("2.00"))

    resp = client.get("/analytics/costs", params={"group_by": "provider"})

    assert resp.status_code == 200
    for row in resp.json():
        assert row["group_details"] is None


def test_costs_group_by_user_includes_soft_deleted_user_details(
    client: TestClient, db: Session
):
    user = _make_user(db)
    _create(db, created_by_id=user.id, cost_estimate_usd=Decimal("3.00"))
    UserRepository(db).delete_user(user.id)

    resp = client.get("/analytics/costs", params={"group_by": "user"})

    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["group_details"] == {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
    }


# ---------------------------------------------------------------------------
# group_key field in response
# ---------------------------------------------------------------------------


def test_costs_group_key_matches_group_by_param(client: TestClient, db: Session):
    _create(db, provider="openai")

    resp = client.get("/analytics/costs", params={"group_by": "provider"})

    assert resp.status_code == 200
    for row in resp.json():
        assert row["group_key"] == "provider"


# ---------------------------------------------------------------------------
# Date range filter
# ---------------------------------------------------------------------------


def test_costs_start_date_excludes_older_records(client: TestClient, db: Session):
    old = _create(db, provider="openai", cost_estimate_usd=Decimal("99.00"))
    # Force created_at to a past date via raw SQL
    db.execute(
        __import__("sqlalchemy").text(
            "UPDATE completion_requests SET created_at = '2020-01-01' WHERE id = :id"
        ),
        {"id": str(old.id)},
    )
    db.flush()
    _create(db, provider="openai", cost_estimate_usd=Decimal("1.00"))

    resp = client.get(
        "/analytics/costs",
        params={"group_by": "provider", "start_date": "2024-01-01"},
    )

    assert resp.status_code == 200
    rows = resp.json()
    by_provider = {row["group_value"]: Decimal(row["total_cost_usd"]) for row in rows}
    assert by_provider.get("openai", Decimal("0")) == Decimal("1.00")


def test_costs_end_date_excludes_future_records(client: TestClient, db: Session):
    future = _create(db, provider="openai", cost_estimate_usd=Decimal("99.00"))
    db.execute(
        __import__("sqlalchemy").text(
            "UPDATE completion_requests SET created_at = '2099-01-01' WHERE id = :id"
        ),
        {"id": str(future.id)},
    )
    db.flush()
    _create(db, provider="openai", cost_estimate_usd=Decimal("1.00"))

    resp = client.get(
        "/analytics/costs",
        params={"group_by": "provider", "end_date": "2026-12-31"},
    )

    assert resp.status_code == 200
    rows = resp.json()
    by_provider = {row["group_value"]: Decimal(row["total_cost_usd"]) for row in rows}
    assert by_provider.get("openai", Decimal("0")) == Decimal("1.00")


# ---------------------------------------------------------------------------
# Dimension filters
# ---------------------------------------------------------------------------


def test_costs_filter_by_project_id(client: TestClient, db: Session):
    _create(
        db,
        project_id="proj-target",
        provider="openai",
        cost_estimate_usd=Decimal("5.00"),
    )
    _create(
        db,
        project_id="proj-other",
        provider="openai",
        cost_estimate_usd=Decimal("99.00"),
    )

    resp = client.get(
        "/analytics/costs",
        params={"group_by": "provider", "project_id": "proj-target"},
    )

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert Decimal(rows[0]["total_cost_usd"]) == Decimal("5.00")


def test_costs_filter_by_provider(client: TestClient, db: Session):
    _create(db, provider="openai", model="gpt-4o", cost_estimate_usd=Decimal("3.00"))
    _create(
        db,
        provider="anthropic",
        model="claude-3-5-sonnet",
        cost_estimate_usd=Decimal("99.00"),
    )

    resp = client.get(
        "/analytics/costs",
        params={"group_by": "model", "provider": "openai"},
    )

    assert resp.status_code == 200
    models = [row["group_value"] for row in resp.json()]
    assert "gpt-4o" in models
    assert "claude-3-5-sonnet" not in models


def test_costs_filter_by_model(client: TestClient, db: Session):
    user_a = _make_user(db)
    user_b = _make_user(db)
    _create(
        db, model="gpt-4o", created_by_id=user_a.id, cost_estimate_usd=Decimal("2.00")
    )
    _create(
        db,
        model="gpt-3.5-turbo",
        created_by_id=user_b.id,
        cost_estimate_usd=Decimal("99.00"),
    )

    resp = client.get(
        "/analytics/costs",
        params={"group_by": "user", "model": "gpt-4o"},
    )

    assert resp.status_code == 200
    users = [str(row["group_value"]) for row in resp.json()]
    assert str(user_a.id) in users
    assert str(user_b.id) not in users


def test_costs_filter_by_created_by_id(client: TestClient, db: Session):
    user_a = _make_user(db)
    user_b = _make_user(db)
    _create(
        db,
        created_by_id=user_a.id,
        provider="openai",
        cost_estimate_usd=Decimal("4.00"),
    )
    _create(
        db,
        created_by_id=user_b.id,
        provider="openai",
        cost_estimate_usd=Decimal("99.00"),
    )

    resp = client.get(
        "/analytics/costs",
        params={"group_by": "provider", "created_by_id": str(user_a.id)},
    )

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert Decimal(rows[0]["total_cost_usd"]) == Decimal("4.00")


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


def test_costs_default_limit_is_10(client: TestClient, db: Session):
    for _ in range(12):
        _create(
            db,
            provider=f"provider-{uuid4().hex[:6]}",
            cost_estimate_usd=Decimal("1.00"),
        )

    resp = client.get("/analytics/costs", params={"group_by": "provider"})

    assert resp.status_code == 200
    assert len(resp.json()) == 10


def test_costs_limit_param_is_respected(client: TestClient, db: Session):
    for _ in range(5):
        _create(
            db,
            provider=f"provider-{uuid4().hex[:6]}",
            cost_estimate_usd=Decimal("1.00"),
        )

    resp = client.get("/analytics/costs", params={"group_by": "provider", "limit": 3})

    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_costs_limit_above_max_returns_422(client: TestClient):
    resp = client.get("/analytics/costs", params={"group_by": "provider", "limit": 101})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_costs_missing_group_by_returns_422(client: TestClient):
    resp = client.get("/analytics/costs")
    assert resp.status_code == 422


def test_costs_invalid_group_by_returns_422(client: TestClient):
    resp = client.get("/analytics/costs", params={"group_by": "invalid_dimension"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------


def test_costs_empty_when_no_records(client: TestClient):
    resp = client.get("/analytics/costs", params={"group_by": "provider"})
    assert resp.status_code == 200
    assert resp.json() == []
