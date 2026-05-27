import pytest
from uuid import uuid4
from sqlalchemy.orm import Session
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.schemas.completion_request import CompletionRequestCreate


@pytest.fixture
def sample_data():
    return CompletionRequestCreate(
        request_id=str(uuid4()),
        project_id=str(uuid4()),
        model_config_slug="gpt4-default",
        provider="openai",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
        latency_ms=320,
        cost_estimate_usd=0,
    )


def test_create(db: Session, sample_data):
    record = CompletionRequestRepository(db).create(sample_data)

    assert record.id is not None
    assert record.request_id == sample_data.request_id
    assert record.model_config_slug == "gpt4-default"
    assert record.input_tokens == 100
    assert record.output_tokens == 50
    assert record.latency_ms == 320
    assert record.created_at is not None


def test_create_with_created_by_id(db: Session, sample_data, setup_user):
    data = sample_data.model_copy(update={"created_by_id": setup_user.id})
    record = CompletionRequestRepository(db).create(data)

    assert record.created_by_id == setup_user.id


def test_create_multiple(db: Session, sample_data):
    repo = CompletionRequestRepository(db)
    second = sample_data.model_copy(update={"request_id": str(uuid4())})

    r1 = repo.create(sample_data)
    r2 = repo.create(second)

    assert r1.id != r2.id
