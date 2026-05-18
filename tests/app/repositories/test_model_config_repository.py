import pytest
from sqlalchemy.orm import Session
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository


@pytest.fixture
def base_data():
    return {
        "slug": "gpt4-default",
        "name": "GPT-4 Default",
        "provider": "openai",
        "model": "gpt-4o",
        "is_default": False,
    }


@pytest.fixture
def sample_config(db: Session, base_data):
    return ModelConfigRepository(db).create(base_data)


def test_create(db: Session, base_data):
    config = ModelConfigRepository(db).create(base_data)

    assert config.id is not None
    assert config.slug == base_data["slug"]
    assert config.provider == "openai"
    assert config.model == "gpt-4o"
    assert config.is_default is False
    assert config.deleted_at is None
    assert config.created_at is not None


def test_get_by_id(db: Session, sample_config):
    found = ModelConfigRepository(db).get_by_id(sample_config.id)

    assert found is not None
    assert found.id == sample_config.id


def test_get_by_id_not_found(db: Session):
    from uuid import uuid4

    assert ModelConfigRepository(db).get_by_id(uuid4()) is None


def test_get_by_id_excludes_soft_deleted(db: Session, sample_config):
    repo = ModelConfigRepository(db)
    repo.delete_record(sample_config.id)

    assert repo.get_by_id(sample_config.id) is None


def test_get_by_slug(db: Session, sample_config):
    found = ModelConfigRepository(db).get_by_slug(sample_config.slug)

    assert found is not None
    assert found.id == sample_config.id


def test_get_by_slug_not_found(db: Session):
    assert ModelConfigRepository(db).get_by_slug("nonexistent") is None


def test_get_by_slug_excludes_soft_deleted(db: Session, sample_config):
    repo = ModelConfigRepository(db)
    repo.delete_record(sample_config.id)

    assert repo.get_by_slug(sample_config.slug) is None


def test_get_default(db: Session):
    ModelConfigRepository(db).create(
        {
            "slug": "my-default",
            "name": "Default",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        }
    )

    found = ModelConfigRepository(db).get_default()

    assert found is not None
    assert found.is_default is True
    assert found.slug == "my-default"


def test_get_default_returns_none_when_none_set(db: Session, sample_config):
    assert ModelConfigRepository(db).get_default() is None


def test_create_clears_previous_default(db: Session):
    repo = ModelConfigRepository(db)
    repo.create(
        {
            "slug": "first",
            "name": "First",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        }
    )
    repo.create(
        {
            "slug": "second",
            "name": "Second",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        }
    )

    defaults = (
        db.query(ModelConfig)
        .filter(ModelConfig.is_default.is_(True), ModelConfig.deleted_at.is_(None))
        .all()
    )
    assert len(defaults) == 1
    assert defaults[0].slug == "second"


def test_update_clears_previous_default(db: Session):
    repo = ModelConfigRepository(db)
    first = repo.create(
        {
            "slug": "first",
            "name": "First",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": True,
        }
    )
    second = repo.create(
        {
            "slug": "second",
            "name": "Second",
            "provider": "openai",
            "model": "gpt-4o",
            "is_default": False,
        }
    )

    repo.update(second, {"is_default": True})

    defaults = (
        db.query(ModelConfig)
        .filter(ModelConfig.is_default.is_(True), ModelConfig.deleted_at.is_(None))
        .all()
    )
    assert len(defaults) == 1
    assert defaults[0].slug == "second"


def test_list_all(db: Session, sample_config):
    configs = ModelConfigRepository(db).list_all()

    assert any(c.id == sample_config.id for c in configs)


def test_list_all_excludes_soft_deleted(db: Session, sample_config):
    repo = ModelConfigRepository(db)
    repo.delete_record(sample_config.id)

    configs = repo.list_all()

    assert not any(c.id == sample_config.id for c in configs)


def test_update(db: Session, sample_config):
    repo = ModelConfigRepository(db)
    updated = repo.update(sample_config, {"name": "Updated Name", "max_tokens": 1000})

    assert updated.name == "Updated Name"
    assert updated.max_tokens == 1000
    assert updated.slug == sample_config.slug


def test_delete_record_soft_deletes(db: Session, sample_config):
    repo = ModelConfigRepository(db)
    repo.delete_record(sample_config.id)

    assert repo.get_by_slug(sample_config.slug) is None

    still_in_db = (
        db.query(ModelConfig)
        .execution_options(skip_soft_delete_filter=True)
        .filter(ModelConfig.id == sample_config.id)
        .first()
    )
    assert still_in_db is not None
    assert still_in_db.deleted_at is not None


# --- config_type tests ---


def test_get_default_for_type_returns_matching(db: Session):
    repo = ModelConfigRepository(db)
    repo.create(
        {
            "slug": "summary-default",
            "name": "Summary Default",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "summary",
            "is_default": True,
        }
    )

    found = repo.get_default_for_type("summary")

    assert found is not None
    assert found.slug == "summary-default"
    assert found.config_type == "summary"


def test_get_default_for_type_returns_none_when_none_set(db: Session):
    assert ModelConfigRepository(db).get_default_for_type("summary") is None


def test_get_default_for_type_ignores_other_types(db: Session):
    repo = ModelConfigRepository(db)
    repo.create(
        {
            "slug": "chat-default",
            "name": "Chat Default",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "chat",
            "is_default": True,
        }
    )

    assert repo.get_default_for_type("summary") is None


def test_clear_default_scoped_to_type(db: Session):
    repo = ModelConfigRepository(db)
    chat_config = repo.create(
        {
            "slug": "chat-default",
            "name": "Chat Default",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "chat",
            "is_default": True,
        }
    )
    repo.create(
        {
            "slug": "summary-default",
            "name": "Summary Default",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "summary",
            "is_default": True,
        }
    )

    # Setting a new summary default should NOT clear the chat default
    repo.create(
        {
            "slug": "summary-default-2",
            "name": "Summary Default 2",
            "provider": "openai",
            "model": "gpt-4o",
            "config_type": "summary",
            "is_default": True,
        }
    )

    db.refresh(chat_config)
    assert chat_config.is_default is True

    summary_defaults = (
        db.query(ModelConfig)
        .filter(
            ModelConfig.config_type == "summary",
            ModelConfig.is_default.is_(True),
            ModelConfig.deleted_at.is_(None),
        )
        .all()
    )
    assert len(summary_defaults) == 1
    assert summary_defaults[0].slug == "summary-default-2"
