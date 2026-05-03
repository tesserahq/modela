import logging
from sqlalchemy.orm import Session
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.model_config import ModelConfigCreate, ModelConfigResponse


class CreateModelConfigCommand:
    def __init__(self, db: Session):
        self.db = db
        self.model_config_repository = ModelConfigRepository(db)
        self.logger = logging.getLogger(__name__)

    def execute(self, data: ModelConfigCreate) -> ModelConfigResponse:
        try:
            record = self.model_config_repository.create(data.model_dump())
            return ModelConfigResponse.model_validate(record)
        except Exception as e:
            self.db.rollback()
            raise Exception(f"Failed to create model config: {str(e)}")
