import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commands.model_configs.create_model_config_command import (
    CreateModelConfigCommand,
)
from app.commands.model_configs.delete_model_config_command import (
    DeleteModelConfigCommand,
)
from app.commands.model_configs.update_model_config_command import (
    UpdateModelConfigCommand,
)
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.model_config import (
    ModelConfigCreate,
    ModelConfigResponse,
    ModelConfigUpdate,
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

    assert ModelConfigRepository(db).get_by_id(existing_config.id) is None


# --- embedding config_type params validation ---


def _embedding_payload(**params_overrides):
    params = {"chunk_size": 500, "chunk_overlap": 50, "strategy": "fixed_size"}
    params.update(params_overrides)
    return ModelConfigCreate(
        slug=f"embed-{params_overrides.get('slug', 'default')}",
        name="Embedding Config",
        provider="openai",
        model="text-embedding-3-small",
        config_type="embedding",
        params=params,
    )


def test_create_embedding_config_with_valid_params_succeeds(db: Session):
    result = CreateModelConfigCommand(db).execute(_embedding_payload())
    assert result.config_type == "embedding"
    assert result.params == {
        "chunk_size": 500,
        "chunk_overlap": 50,
        "strategy": "fixed_size",
    }


def test_create_embedding_config_requires_params(db: Session):
    payload = ModelConfigCreate(
        slug="embed-no-params",
        name="Embedding Config",
        provider="openai",
        model="text-embedding-3-small",
        config_type="embedding",
    )
    with pytest.raises(InvalidParameterError):
        CreateModelConfigCommand(db).execute(payload)


def test_create_embedding_config_rejects_overlap_gte_chunk_size(db: Session):
    payload = _embedding_payload(chunk_size=100, chunk_overlap=100)
    with pytest.raises(InvalidParameterError):
        CreateModelConfigCommand(db).execute(payload)


def test_create_embedding_config_rejects_unknown_strategy(db: Session):
    payload = _embedding_payload(strategy="semantic")
    with pytest.raises(InvalidParameterError):
        CreateModelConfigCommand(db).execute(payload)


def test_create_embedding_config_rejects_chunk_size_out_of_range(db: Session):
    payload = _embedding_payload(chunk_size=100)  # below the 256 minimum
    with pytest.raises(InvalidParameterError):
        CreateModelConfigCommand(db).execute(payload)


def test_non_embedding_config_type_ignores_params_validation(
    db: Session, create_payload
):
    # config_type="chat" (the default) never requires/validates `params`.
    result = CreateModelConfigCommand(db).execute(create_payload)
    assert result.params is None


# --- one default per config_type (regression test for the PRD 0019 review's
# claim, verified during implementation planning to already be enforced at
# the DB level by migration 2026_05_18_0006 + IntegrityError->ConflictError
# handling in these commands) ---


def test_two_default_embedding_configs_violate_db_constraint(db: Session):
    """CreateModelConfigCommand's _clear_default-then-insert sequence handles
    sequential requests fine (each clear happens before the next insert), so
    this exercises the DB-level partial unique index directly — the scenario
    a real race between two concurrent requests could produce."""
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            ModelConfig(
                slug="embed-a",
                name="A",
                provider="openai",
                model="text-embedding-3-small",
                config_type="embedding",
                is_default=True,
            )
        )
        db.add(
            ModelConfig(
                slug="embed-b",
                name="B",
                provider="openai",
                model="text-embedding-3-small",
                config_type="embedding",
                is_default=True,
            )
        )
        db.flush()
