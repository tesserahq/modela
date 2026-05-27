from typing import Optional
from uuid import UUID
from app.models.model_config import ModelConfig
from app.inference.adapters.registry import get_adapter
from app.inference.model import ModelaModel


def build_model(
    config: ModelConfig,
    project_id: str,
    request_id: str,
    *,
    user_id: Optional[UUID] = None,
) -> ModelaModel:
    adapter = get_adapter(config.provider)
    inner = adapter.create_model(config.model)
    return ModelaModel(inner, config, project_id, request_id, user_id=user_id)
