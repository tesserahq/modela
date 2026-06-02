from __future__ import annotations

from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.mcp_server import MCPServer

from app.db import get_db
from app.models.completion_request import CompletionRequest
from app.models.model_config import ModelConfig
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.repositories.mcp_server_repository import MCPServerRepository
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


def get_mcp_server_by_id(
    id: UUID,
    db: Session = Depends(get_db),
) -> MCPServer:
    """FastAPI dependency to get an MCP server by ID."""
    mcp_server = MCPServerRepository(db).get_mcp_server(id)
    if mcp_server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return mcp_server
