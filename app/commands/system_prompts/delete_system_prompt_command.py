"""Command to delete a system prompt."""

from __future__ import annotations

import logging
from typing import Optional, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.events.system_prompt_events import build_system_prompt_deleted_event
from app.exceptions.conflict_error import ConflictError
from app.models.system_prompt import SystemPrompt
from app.repositories.system_prompt_repository import SystemPromptRepository
from tessera_sdk.infra.events.event import Event  # type: ignore[import-untyped]
from tessera_sdk.infra.events.nats_router import NatsEventPublisher  # type: ignore[import-untyped]


class DeleteSystemPromptCommand:
    """
    Command to delete a system prompt and publish system_prompt.deleted event.
    """

    def __init__(
        self,
        db: Session,
        nats_publisher: Optional[NatsEventPublisher] = None,
    ):
        self.db = db
        self.system_prompt_service = SystemPromptRepository(db)
        self.nats_publisher = (
            nats_publisher if nats_publisher is not None else NatsEventPublisher()
        )
        self.logger = logging.getLogger(__name__)

    def execute(
        self,
        prompt_id: UUID,
        deleted_by_id: Optional[UUID] = None,
    ) -> bool:
        """
        Execute the command to delete a system prompt and publish the event.

        Args:
            prompt_id: ID of the system prompt to delete.
            deleted_by_id: Optional user ID of the deleter.

        Returns:
            True if the prompt was deleted, False if not found.
        """
        prompt = self.system_prompt_service.get_system_prompt_by_id(prompt_id)
        if prompt is None:
            return False

        prompt_id = cast(UUID, prompt.id)

        if self.system_prompt_service.is_referenced_by_model_config(prompt_id):
            raise ConflictError(
                f"System prompt '{prompt.name}' is referenced by one or more ModelConfigs"
            )

        deletion_event = build_system_prompt_deleted_event(prompt, deleted_by_id)
        ok = self.system_prompt_service.delete_prompt_by_id(prompt_id)
        if ok:
            self._publish_system_prompt_deleted_event(deletion_event)
        return ok

    def _publish_system_prompt_deleted_event(
        self,
        event: Event,
    ) -> None:
        """Publish a system_prompt.deleted event to NATS."""
        if self.nats_publisher is not None:
            self.logger.info(
                "Publishing system-prompt-deleted event to NATS: %s",
                event.model_dump_json(),
            )
            try:
                self.nats_publisher.publish_sync(event, event.event_type)
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Failed to publish system-prompt-deleted event to NATS"
                )
