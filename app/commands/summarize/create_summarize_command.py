import logging
from uuid import UUID

from pydantic_ai.messages import DocumentUrl
from sqlalchemy.orm import Session

from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.inference import AgentRunner, build_model
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository
from app.schemas.summarize import SummarizeResponse

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = "Summarize the following document concisely."


class CreateSummarizeCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ModelConfigRepository(db)

    async def execute_text(
        self,
        content: str,
        model_slug: str | None,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ) -> SummarizeResponse:
        return await self._execute(
            user_prompt=content,
            model_slug=model_slug,
            project_id=project_id,
            request_id=request_id,
            user_id=user_id,
        )

    async def execute_file(
        self,
        file_url: str,
        mime_type: str,
        model_slug: str | None,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ) -> SummarizeResponse:
        return await self._execute(
            user_prompt=[
                "Please summarize the following document.",
                DocumentUrl(url=file_url, media_type=mime_type),
            ],
            model_slug=model_slug,
            project_id=project_id,
            request_id=request_id,
            user_id=user_id,
        )

    async def _execute(
        self,
        user_prompt: str | list,
        model_slug: str | None,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ) -> SummarizeResponse:
        config = self._resolve_config(model_slug)
        model = build_model(config, project_id, request_id)

        system_prompt_content = _DEFAULT_SYSTEM_PROMPT
        if config.system_prompt_id is not None:
            resolved = SystemPromptRepository(self.db).get_current_content_by_id(
                config.system_prompt_id
            )
            if resolved is not None:
                system_prompt_content = resolved

        result = await AgentRunner(model).run(
            user_prompt,
            system_prompt=system_prompt_content,
        )

        logger.info(
            "summarize complete",
            extra={
                "request_id": request_id,
                "config_slug": config.slug,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )

        return SummarizeResponse(
            summary=result.output,
            model=config.slug,
            request_id=request_id,
        )

    def _resolve_config(self, model_slug: str | None):
        if model_slug:
            config = self.repo.get_by_slug(model_slug)
            if config is None:
                raise ResourceNotFoundError(f"ModelConfig '{model_slug}' not found")
            return config
        config = self.repo.get_default_for_type("summary")
        if config is None:
            raise ResourceNotFoundError(
                "No default 'summary' ModelConfig is configured"
            )
        return config
