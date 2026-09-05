import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions.conflict_error import ConflictError
from app.inference.adapters.parameter_validation import validate_model_config_parameters
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.embedding_config_params import validate_embedding_config_params
from app.schemas.model_config import ModelConfigCreate, ModelConfigResponse
from app.services.tools.registry import validate_enabled_tools


class CreateModelConfigCommand:
    def __init__(self, db: Session):
        self.db = db
        self.model_config_repository = ModelConfigRepository(db)
        self.logger = logging.getLogger(__name__)

    def execute(self, data: ModelConfigCreate) -> ModelConfigResponse:
        validate_model_config_parameters(
            data.provider,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            top_p=data.top_p,
        )
        validate_embedding_config_params(data.config_type, data.params)
        validate_enabled_tools(data.enabled_tools)
        try:
            record = self.model_config_repository.create(data.model_dump())
            return ModelConfigResponse.model_validate(record)
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(
                f"A model config with slug '{data.slug}' already exists."
            )
