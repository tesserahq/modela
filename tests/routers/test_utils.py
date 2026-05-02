import pytest
from uuid import uuid4
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository
from app.routers.utils.dependencies import get_model_config_by_id
from app.exceptions.resource_not_found_error import ResourceNotFoundError


@pytest.fixture
def existing_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "utils-test",
            "name": "Utils Test",
            "provider": "openai",
            "model": "gpt-4o",
        }
    )


def test_get_model_config_by_id_returns_record(db: Session, existing_config):
    result = get_model_config_by_id(id=existing_config.id, db=db)

    assert result.id == existing_config.id
    assert result.slug == "utils-test"


def test_get_model_config_by_id_raises_for_unknown_id(db: Session):
    with pytest.raises(ResourceNotFoundError):
        get_model_config_by_id(id=uuid4(), db=db)


def test_get_model_config_by_id_raises_for_deleted(db: Session, existing_config):
    ModelConfigRepository(db).delete_record(existing_config.id)

    with pytest.raises(ResourceNotFoundError):
        get_model_config_by_id(id=existing_config.id, db=db)
