import logging
from uuid import UUID

from pydantic_ai.messages import DocumentUrl
from sqlalchemy.orm import Session

from app.commands.completions.schema_to_model import schema_to_model
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.inference import AgentRunner, build_model
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository
from app.schemas.scan import ScanResponse
from app.utils.url_validation import validate_file_url

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "Extract the requested fields from the document. "
    "Return only the structured data specified in the schema."
)


class CreateScanCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ModelConfigRepository(db)

    async def execute_file(
        self,
        file_url: str,
        mime_type: str,
        model_slug: str | None,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ) -> ScanResponse:
        config = self._resolve_config(model_slug)

        validate_file_url(file_url)

        if not config.output_schema:
            raise InvalidParameterError(
                f"ModelConfig '{config.slug}' has no output_schema configured. "
                "Set an output_schema on the ModelConfig before using the scan endpoint."
            )

        output_type = schema_to_model(config.output_schema)
        model = build_model(config, project_id, request_id, user_id=user_id)

        system_prompt_content = _DEFAULT_SYSTEM_PROMPT
        if config.system_prompt_id is not None:
            resolved = SystemPromptRepository(self.db).get_current_content_by_id(
                config.system_prompt_id
            )
            if resolved is not None:
                system_prompt_content = resolved

        user_prompt = [
            "Please extract the requested information from the following document.",
            DocumentUrl(url=file_url, media_type=mime_type),
        ]

        result = await AgentRunner(model).run(
            user_prompt,
            system_prompt=system_prompt_content,
            output_type=output_type,
        )

        logger.info(
            "scan complete",
            extra={
                "request_id": request_id,
                "config_slug": config.slug,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )

        return ScanResponse(
            data=result.output,
            model=config.slug,
            request_id=request_id,
        )

    def _resolve_config(self, model_slug: str | None):
        if model_slug:
            config = self.repo.get_by_slug(model_slug)
            if config is None:
                raise ResourceNotFoundError(f"ModelConfig '{model_slug}' not found")
            return config
        config = self.repo.get_default_for_type("scan")
        if config is None:
            raise ResourceNotFoundError("No default 'scan' ModelConfig is configured")
        return config
