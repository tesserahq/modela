from fastapi import APIRouter, Depends, status
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session
from app.db import get_db
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
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository
from app.routers.utils.dependencies import get_model_config_by_id
from app.schemas.model_config import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
)
from app.exceptions.resource_not_found_error import ResourceNotFoundError
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
