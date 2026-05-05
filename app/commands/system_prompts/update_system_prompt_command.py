"""Command to update a system prompt and conditionally create a new version."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.events.system_prompt_events import build_system_prompt_updated_event
from app.models.system_prompt import SystemPrompt
from app.schemas.system_prompt import SystemPromptUpdate
from app.repositories.system_prompt_repository import SystemPromptRepository
from tessera_sdk.infra.events.nats_router import NatsEventPublisher  # type: ignore[import-untyped]


class UpdateSystemPromptCommand:
    """
    Command to update a system prompt attributes and conditionally create a new current version
    and publish system_prompt.updated event.
    """

    def __init__(
        self,
        db: Session,
        nats_publisher: Optional[NatsEventPublisher] = None,
    ):
        self.db = db
        self.system_prompt_repository = SystemPromptRepository(db)
        self.nats_publisher = (
            nats_publisher if nats_publisher is not None else NatsEventPublisher()
        )
        self.logger = logging.getLogger(__name__)

    def execute(
        self,
        prompt_id: UUID,
        data: SystemPromptUpdate,
        updated_by_id: Optional[UUID] = None,
    ) -> Optional[SystemPrompt]:
        """
        Execute the command to update prompt attributes, create a new version only when
        content changes, and publish the event.
        and publish the event.

        Args:
            prompt_id: ID of the system prompt to update.
            data: The update data (name and/or content).
            updated_by_id: Optional user ID of the updater.

        Returns:
            The updated system prompt, or None if not found.

        Raises:
            ValueError: If new name already exists.
        """
        prompt = self.system_prompt_repository.get_system_prompt_by_id(prompt_id)
        if prompt is None:
            return None

        if data.name is not None:
            prompt = self.system_prompt_repository.update_prompt_name_by_id(
                prompt_id, new_name=data.name
            )
            if prompt is None:
                return None

        current_content = self.system_prompt_repository.get_current_content_by_id(
            prompt_id
        )
        if data.content is not None and data.content != (current_content or ""):
            version = self.system_prompt_repository.create_version(
                prompt_id,
                content=data.content,
                note=data.note,
            )
            if version is None:
                return None

        prompt = self.system_prompt_repository.get_system_prompt_by_id(prompt_id)
        if prompt is not None:
            self._publish_system_prompt_updated_event(prompt, updated_by_id)
        return prompt

    def _publish_system_prompt_updated_event(
        self,
        prompt: SystemPrompt,
        updated_by_id: Optional[UUID],
    ) -> None:
        """Publish a system_prompt.updated event to NATS."""
        event = build_system_prompt_updated_event(prompt, updated_by_id)
        if self.nats_publisher is not None:
            self.logger.info(
                "Publishing system-prompt-updated event to NATS: %s",
                event.model_dump_json(),
            )
            try:
                self.nats_publisher.publish_sync(event, event.event_type)
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Failed to publish system-prompt-updated event to NATS"
                )
