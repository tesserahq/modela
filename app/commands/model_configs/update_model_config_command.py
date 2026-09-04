import logging
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.exceptions.conflict_error import ConflictError
from app.inference.adapters.parameter_validation import validate_model_config_parameters
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.embedding_config_params import validate_embedding_config_params
from app.schemas.model_config import ModelConfigUpdate, ModelConfigResponse


class UpdateModelConfigCommand:
    def __init__(self, db: Session):
        self.db = db
        self.model_config_repository = ModelConfigRepository(db)
        self.logger = logging.getLogger(__name__)

    def execute(
        self, record: ModelConfig, data: ModelConfigUpdate
    ) -> ModelConfigResponse:
        updates = data.model_dump(exclude_unset=True)
        validate_model_config_parameters(
            updates.get("provider", record.provider),
            temperature=updates.get("temperature", record.temperature),
            max_tokens=updates.get("max_tokens", record.max_tokens),
            top_p=updates.get("top_p", record.top_p),
        )
        validate_embedding_config_params(
            updates.get("config_type", record.config_type),
            updates.get("params", record.params),
        )
        try:
            updated = self.model_config_repository.update(
                record, data.model_dump(exclude_unset=True)
            )
            return ModelConfigResponse.model_validate(updated)
        except IntegrityError:
            self.db.rollback()
            slug = data.slug if data.slug is not None else record.slug
            raise ConflictError(f"A model config with slug '{slug}' already exists.")
