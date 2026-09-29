import logging
from sqlalchemy.orm import Session
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository


class DeleteModelConfigCommand:
    def __init__(self, db: Session):
        self.db = db
        self.model_config_repository = ModelConfigRepository(db)
        self.logger = logging.getLogger(__name__)

    def execute(self, record: ModelConfig) -> None:
        self.model_config_repository.delete_record(record.id)
