from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.models.system_prompt import SystemPrompt
from app.schemas.system_prompt import SystemPromptRead
from tessera_sdk.infra.events.event import Event, event_type, event_source  # type: ignore[import-untyped]

SYSTEM_PROMPT_CREATED = "modela.system_prompt.created"
SYSTEM_PROMPT_UPDATED = "modela.system_prompt.updated"
SYSTEM_PROMPT_DELETED = "modela.system_prompt.deleted"


def build_system_prompt_created_event(
    prompt: SystemPrompt,
    created_by_id: Optional[UUID] = None,
) -> Event:
    data = SystemPromptRead.model_validate(prompt).model_dump(mode="json")
    return Event(
        source=event_source(f"/system-prompts/{prompt.id}"),
        event_type=event_type(SYSTEM_PROMPT_CREATED),
        privy=True,
        event_data={"system_prompt": data},
        subject=f"/system-prompts/{prompt.id}",
        user_id=str(created_by_id) if created_by_id else None,
        labels={
            "system_prompt_id": str(prompt.id),
            "name": prompt.name,
            "action": "created",
        },
        tags=[f"system_prompt_id:{prompt.id}", f"name:{prompt.name}", "action:created"],
    )


def build_system_prompt_updated_event(
    prompt: SystemPrompt,
    updated_by_id: Optional[UUID] = None,
) -> Event:
    data = SystemPromptRead.model_validate(prompt).model_dump(mode="json")
    return Event(
        source=event_source(f"/system-prompts/{prompt.id}"),
        event_type=event_type(SYSTEM_PROMPT_UPDATED),
        privy=True,
        event_data={"system_prompt": data},
        subject=f"/system-prompts/{prompt.id}",
        user_id=str(updated_by_id) if updated_by_id else None,
        labels={
            "system_prompt_id": str(prompt.id),
            "name": prompt.name,
            "action": "updated",
        },
        tags=[f"system_prompt_id:{prompt.id}", f"name:{prompt.name}", "action:updated"],
    )


def build_system_prompt_deleted_event(
    prompt: SystemPrompt,
    deleted_by_id: Optional[UUID] = None,
) -> Event:
    data = SystemPromptRead.model_validate(prompt).model_dump(mode="json")
    return Event(
        source=event_source(f"/system-prompts/{prompt.id}"),
        event_type=event_type(SYSTEM_PROMPT_DELETED),
        privy=True,
        event_data={"system_prompt": data},
        subject=f"/system-prompts/{prompt.id}",
        user_id=str(deleted_by_id) if deleted_by_id else None,
        labels={
            "system_prompt_id": str(prompt.id),
            "name": prompt.name,
            "action": "deleted",
        },
        tags=[f"system_prompt_id:{prompt.id}", f"name:{prompt.name}", "action:deleted"],
    )
