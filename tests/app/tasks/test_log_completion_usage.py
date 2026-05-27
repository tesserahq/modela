from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.completion_request import CompletionRequest
from app.tasks.log_completion_usage import log_completion_usage


def _run_task(db: Session, **overrides):
    defaults = dict(
        request_id=str(uuid4()),
        project_id="proj-test",
        model_config_slug="default-chat",
        provider="openai",
        model="gpt-4o",
        input_tokens=1000,
        output_tokens=500,
        finish_reason="stop",
        latency_ms=120,
        created_by_id=None,
    )
    defaults.update(overrides)

    with patch("app.tasks.log_completion_usage.SessionLocal", return_value=db):
        with patch.object(db, "close"):
            log_completion_usage(**defaults)

    return defaults["request_id"]


def _get_by_request_id(db: Session, request_id: str) -> CompletionRequest:
    return db.execute(
        select(CompletionRequest).where(CompletionRequest.request_id == request_id)
    ).scalar_one()


def test_known_model_writes_nonzero_cost(db: Session):
    request_id = _run_task(db, provider="openai", model="gpt-4o")

    record = _get_by_request_id(db, request_id)
    assert record.cost_estimate_usd > Decimal("0")


def test_unknown_model_writes_zero_cost(db: Session):
    request_id = _run_task(db, provider="openai", model="not-a-real-model-xyz")

    record = _get_by_request_id(db, request_id)
    assert record.cost_estimate_usd == Decimal("0")


def test_token_counts_stored_correctly(db: Session):
    request_id = _run_task(db, input_tokens=42, output_tokens=7)

    record = _get_by_request_id(db, request_id)
    assert record.input_tokens == 42
    assert record.output_tokens == 7


def test_created_by_id_stored_when_provided(db: Session, setup_user):
    request_id = _run_task(db, created_by_id=str(setup_user.id))

    record = _get_by_request_id(db, request_id)
    assert record.created_by_id == setup_user.id


def test_created_by_id_null_when_omitted(db: Session):
    request_id = _run_task(db)

    record = _get_by_request_id(db, request_id)
    assert record.created_by_id is None
