import logging
from sqlalchemy.orm import Session
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.model_config import ModelConfigUpdate, ModelConfigResponse


class UpdateModelConfigCommand:
    def __init__(self, db: Session):
        self.db = db
        self.model_config_repository = ModelConfigRepository(db)
        self.logger = logging.getLogger(__name__)

    def execute(
        self, record: ModelConfig, data: ModelConfigUpdate
    ) -> ModelConfigResponse:
        try:
            updated = self.model_config_repository.update(
                record, data.model_dump(exclude_unset=True)
            )
            return ModelConfigResponse.model_validate(updated)
        except Exception as e:
            self.db.rollback()
            raise Exception(f"Failed to update model config: {str(e)}")
