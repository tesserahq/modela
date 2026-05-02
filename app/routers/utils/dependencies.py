from __future__ import annotations

from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.completion_request import CompletionRequest
from app.models.model_config import ModelConfig
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.exceptions.resource_not_found_error import ResourceNotFoundError


def get_model_config_by_id(
    id: UUID,
    db: Session = Depends(get_db),
) -> ModelConfig:
    model_config = ModelConfigRepository(db).get_by_id(id)
    if model_config is None:
        raise ResourceNotFoundError(f"ModelConfig '{id}' not found")
    return model_config


def get_completion_request_by_id(
    id: UUID,
    db: Session = Depends(get_db),
) -> CompletionRequest:
    record = CompletionRequestRepository(db).get_by_id(id)
    if record is None:
        raise ResourceNotFoundError(f"CompletionRequest '{id}' not found")
    return record
