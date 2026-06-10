from typing import get_args
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi_pagination import Page
from fastapi_pagination import paginate as paginate_sequence
from fastapi_pagination.utils import disable_installed_extensions_check

disable_installed_extensions_check()
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies, infer_domain
from app.commands.model_configs.create_model_config_command import (
    CreateModelConfigCommand,
)
from app.commands.model_configs.update_model_config_command import (
    UpdateModelConfigCommand,
)
from app.commands.model_configs.delete_model_config_command import (
    DeleteModelConfigCommand,
)
from app.db import get_db
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.models.model_config import ModelConfig
from app.repositories.mcp_server_repository import MCPServerRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.routers.utils.dependencies import get_model_config_by_id
from app.schemas.mcp_server import MCPServerRead
from app.schemas.model_config import (
    ConfigType,
    ConfigTypeRead,
    MCPServerAttachRequest,
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
)
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(prefix="/model-configs", tags=["model-configs"])
RBAC_RESOURCE = "model_config"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, domain_resolver=infer_domain)


@router.post(
    "",
    response_model=ModelConfigResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_rbac["create"]), Depends(get_current_user)],
)
def create_model_config(
    payload: ModelConfigCreate,
    db: Session = Depends(get_db),
):
    return CreateModelConfigCommand(db).execute(payload)


@router.get(
    "",
    response_model=Page[ModelConfigResponse],
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def list_model_configs(db: Session = Depends(get_db)):
    query = ModelConfigRepository(db).list_query()
    return paginate(db, query)


@router.get(
    "/types",
    response_model=Page[ConfigTypeRead],
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def list_model_config_types():
    return paginate_sequence([ConfigTypeRead.from_id(t) for t in get_args(ConfigType)])


@router.get(
    "/{id}",
    response_model=ModelConfigResponse,
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def get_model_config(config: ModelConfig = Depends(get_model_config_by_id)):
    return ModelConfigResponse.model_validate(config)


@router.put(
    "/{id}",
    response_model=ModelConfigResponse,
    dependencies=[Depends(_rbac["update"]), Depends(get_current_user)],
)
def update_model_config(
    payload: ModelConfigUpdate,
    config: ModelConfig = Depends(get_model_config_by_id),
    db: Session = Depends(get_db),
):
    return UpdateModelConfigCommand(db).execute(config, payload)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_rbac["delete"]), Depends(get_current_user)],
)
def delete_model_config(
    config: ModelConfig = Depends(get_model_config_by_id),
    db: Session = Depends(get_db),
):
    DeleteModelConfigCommand(db).execute(config)


@router.post(
    "/{id}/mcp-servers",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_rbac["update"]), Depends(get_current_user)],
)
def attach_mcp_server(
    payload: MCPServerAttachRequest,
    config: ModelConfig = Depends(get_model_config_by_id),
    db: Session = Depends(get_db),
):
    server = MCPServerRepository(db).get_mcp_server(payload.server_id)
    if server is None:
        raise ResourceNotFoundError(f"MCPServer '{payload.server_id}' not found")
    if server not in config.mcp_servers:
        config.mcp_servers.append(server)
        db.commit()
    return {}


@router.delete(
    "/{id}/mcp-servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_rbac["update"]), Depends(get_current_user)],
)
def detach_mcp_server(
    server_id: UUID,
    config: ModelConfig = Depends(get_model_config_by_id),
    db: Session = Depends(get_db),
):
    server = next((s for s in config.mcp_servers if s.id == server_id), None)
    if server is None:
        raise ResourceNotFoundError(
            f"MCPServer '{server_id}' is not attached to this ModelConfig"
        )
    config.mcp_servers.remove(server)
    db.commit()


@router.get(
    "/{id}/mcp-servers",
    response_model=Page[MCPServerRead],
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def list_attached_mcp_servers(
    config: ModelConfig = Depends(get_model_config_by_id),
    db: Session = Depends(get_db),
):
    query = MCPServerRepository(db).list_query_for_model_config(config.id)
    return paginate(db, query)
