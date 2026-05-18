from typing import Optional, List
from uuid import UUID
from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from app.models.model_config import ModelConfig
from app.repositories.soft_delete_repository import SoftDeleteRepository


class ModelConfigRepository(SoftDeleteRepository[ModelConfig]):
    def __init__(self, db: Session):
        super().__init__(db, ModelConfig)

    def get_by_id(self, id: UUID) -> Optional[ModelConfig]:
        return (
            self.db.query(ModelConfig)
            .filter(ModelConfig.id == id, ModelConfig.deleted_at.is_(None))
            .first()
        )

    def get_by_slug(self, slug: str) -> Optional[ModelConfig]:
        return (
            self.db.query(ModelConfig)
            .filter(ModelConfig.slug == slug, ModelConfig.deleted_at.is_(None))
            .first()
        )

    def get_default(self) -> Optional[ModelConfig]:
        return (
            self.db.query(ModelConfig)
            .filter(ModelConfig.is_default.is_(True), ModelConfig.deleted_at.is_(None))
            .first()
        )

    def get_default_for_type(self, config_type: str) -> Optional[ModelConfig]:
        return (
            self.db.query(ModelConfig)
            .filter(
                ModelConfig.config_type == config_type,
                ModelConfig.is_default.is_(True),
                ModelConfig.deleted_at.is_(None),
            )
            .first()
        )

    def list_all(self) -> List[ModelConfig]:
        return (
            self.db.query(ModelConfig)
            .filter(ModelConfig.deleted_at.is_(None))
            .order_by(ModelConfig.created_at.desc())
            .all()
        )

    def list_query(self) -> Select:
        return (
            select(ModelConfig)
            .filter(ModelConfig.deleted_at.is_(None))
            .order_by(ModelConfig.created_at.desc())
        )

    def create(self, data: dict) -> ModelConfig:
        if data.get("is_default"):
            self._clear_default(config_type=data.get("config_type", "chat"))
        record = ModelConfig(**data)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def update(self, record: ModelConfig, data: dict) -> ModelConfig:
        if data.get("is_default"):
            config_type = data.get("config_type", record.config_type)
            self._clear_default(config_type=config_type, exclude_id=record.id)
        for key, value in data.items():
            setattr(record, key, value)
        self.db.commit()
        self.db.refresh(record)
        return record

    def _clear_default(
        self, config_type: str, exclude_id: Optional[UUID] = None
    ) -> None:
        q = self.db.query(ModelConfig).filter(
            ModelConfig.config_type == config_type,
            ModelConfig.is_default.is_(True),
            ModelConfig.deleted_at.is_(None),
        )
        if exclude_id is not None:
            q = q.filter(ModelConfig.id != exclude_id)
        q.update({"is_default": False}, synchronize_session="fetch")
        self.db.flush()
