"""System prompts API: CRUD and version management with RBAC."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies, infer_domain
from app.commands.system_prompts import (
    CreateSystemPromptCommand,
    DeleteSystemPromptCommand,
    UpdateSystemPromptCommand,
)
from app.db import get_db
from app.schemas.system_prompt import (
    SystemPromptCreate,
    SystemPromptCurrentRead,
    SystemPromptRead,
    SystemPromptUpdate,
    SystemPromptVersionCreate,
    SystemPromptVersionRead,
)
from app.repositories.system_prompt_repository import SystemPromptRepository
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(
    prefix="/system-prompts",
    tags=["system-prompts"],
    responses={404: {"description": "Not found"}},
)


RESOURCE_PROMPTS = "system_prompt"
rbac_prompts = build_rbac_dependencies(
    resource=RESOURCE_PROMPTS,
    domain_resolver=infer_domain,
)


@router.get(
    "",
    response_model=Page[SystemPromptRead],
)
def list_system_prompts(
    _authorized: bool = Depends(rbac_prompts["read"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[SystemPromptRead]:
    """List all system prompts with pagination."""
    svc = SystemPromptRepository(db)
    return paginate(db, svc.get_system_prompts_query())


@router.post(
    "",
    response_model=SystemPromptRead,
    status_code=201,
)
def create_system_prompt(
    data: SystemPromptCreate,
    _authorized: bool = Depends(rbac_prompts["create"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemPromptRead:
    """Create a new system prompt with optional initial content."""
    command = CreateSystemPromptCommand(db)
    prompt = command.execute(
        data,
        created_by_id=getattr(_current_user, "id", None),
    )
    return prompt


@router.get(
    "/{prompt_id}",
    response_model=SystemPromptRead,
)
def get_system_prompt(
    prompt_id: UUID,
    _authorized: bool = Depends(rbac_prompts["read"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemPromptRead:
    """Get a system prompt by ID."""
    svc = SystemPromptRepository(db)
    prompt = svc.get_system_prompt_by_id(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    return prompt


@router.put(
    "/{prompt_id}",
    response_model=SystemPromptRead,
)
def update_system_prompt(
    prompt_id: UUID,
    data: SystemPromptUpdate,
    _authorized: bool = Depends(rbac_prompts["update"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemPromptRead:
    """Update a system prompt by ID (e.g. rename)."""
    command = UpdateSystemPromptCommand(db)
    prompt = command.execute(
        prompt_id,
        data,
        updated_by_id=getattr(_current_user, "id", None),
    )
    if prompt is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    return prompt


@router.delete(
    "/{prompt_id}",
    status_code=204,
)
def delete_system_prompt(
    prompt_id: UUID,
    _authorized: bool = Depends(rbac_prompts["delete"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a system prompt by ID and all its versions."""
    command = DeleteSystemPromptCommand(db)
    if not command.execute(
        prompt_id,
        deleted_by_id=getattr(_current_user, "id", None),
    ):
        raise HTTPException(status_code=404, detail="System prompt not found")


@router.get(
    "/{name}/current",
    response_model=SystemPromptCurrentRead,
)
def get_system_prompt_current(
    name: str,
    _authorized: bool = Depends(rbac_prompts["read"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemPromptCurrentRead:
    """Return the current system prompt content and version info."""
    svc = SystemPromptRepository(db)
    result = svc.get_current_version_display(name)
    if result is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    version, prompt = result
    return SystemPromptCurrentRead(
        content=str(version.content),
        version_id=version.id,
        version_number=int(version.version_number),
        updated_at=prompt.updated_at,
    )


@router.get(
    "/{name}/versions",
    response_model=Page[SystemPromptVersionRead],
)
def list_system_prompt_versions(
    name: str,
    _authorized: bool = Depends(rbac_prompts["read"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[SystemPromptVersionRead]:
    """List version history for the given system prompt, newest first."""
    svc = SystemPromptRepository(db)
    if svc.get_system_prompt_by_name(name) is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    return paginate(db, svc.get_versions_query(name))


@router.post(
    "/{name}/versions",
    response_model=SystemPromptVersionRead,
    status_code=201,
)
def create_system_prompt_version(
    name: str,
    data: SystemPromptVersionCreate,
    _authorized: bool = Depends(rbac_prompts["create"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemPromptVersionRead:
    """Create a new version and set it as the current system prompt."""
    svc = SystemPromptRepository(db)
    prompt = svc.get_system_prompt_by_name(name)
    if prompt is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    version = svc.create_version(prompt.id, content=data.content, note=data.note)
    if version is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    return version
