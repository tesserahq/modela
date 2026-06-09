import pytest
from sqlalchemy.orm import Session
from app.commands.model_configs.create_model_config_command import (
    CreateModelConfigCommand,
)
from app.commands.model_configs.update_model_config_command import (
    UpdateModelConfigCommand,
)
from app.commands.model_configs.delete_model_config_command import (
    DeleteModelConfigCommand,
)
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.model_config import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
)


@pytest.fixture
def create_payload():
    return ModelConfigCreate(
        slug="test-gpt4",
        name="Test GPT-4",
        provider="openai",
        model="gpt-4o",
    )


@pytest.fixture
def existing_config(db: Session):
    return ModelConfigRepository(db).create(
        {
            "slug": "existing",
            "name": "Existing Config",
            "provider": "openai",
            "model": "gpt-4o",
        }
    )


# --- CreateModelConfigCommand ---


def test_create_returns_response(db: Session, create_payload):
    result = CreateModelConfigCommand(db).execute(create_payload)

    assert isinstance(result, ModelConfigResponse)
    assert result.slug == "test-gpt4"
    assert result.provider == "openai"
    assert result.id is not None


def test_create_rejects_anthropic_temperature_above_provider_max(
    db: Session, create_payload
):
    payload = create_payload.model_copy(
        update={
            "slug": "anthropic-invalid",
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "temperature": 1.5,
        }
    )

    with pytest.raises(InvalidParameterError, match="temperature must be <= 1.0"):
        CreateModelConfigCommand(db).execute(payload)


def test_create_persists_to_db(db: Session, create_payload):
    result = CreateModelConfigCommand(db).execute(create_payload)

    persisted = ModelConfigRepository(db).get_by_slug("test-gpt4")
    assert persisted is not None
    assert persisted.id == result.id


# --- UpdateModelConfigCommand ---


def test_update_returns_updated_response(db: Session, existing_config):
    payload = ModelConfigUpdate(name="Renamed Config", max_tokens=500)

    result = UpdateModelConfigCommand(db).execute(existing_config, payload)

    assert isinstance(result, ModelConfigResponse)
    assert result.name == "Renamed Config"
    assert result.max_tokens == 500
    assert result.slug == existing_config.slug


def test_update_rejects_anthropic_temperature_above_provider_max(
    db: Session, existing_config
):
    payload = ModelConfigUpdate(provider="anthropic", temperature=1.5)

    with pytest.raises(InvalidParameterError, match="temperature must be <= 1.0"):
        UpdateModelConfigCommand(db).execute(existing_config, payload)


def test_update_partial_fields_unchanged(db: Session, existing_config):
    original_model = existing_config.model
    payload = ModelConfigUpdate(name="Partial Update")

    result = UpdateModelConfigCommand(db).execute(existing_config, payload)

    assert result.model == original_model


# --- DeleteModelConfigCommand ---


def test_delete_soft_deletes_record(db: Session, existing_config):
    DeleteModelConfigCommand(db).execute(existing_config)

    assert ModelConfigRepository(db).get_by_slug(existing_config.slug) is None
