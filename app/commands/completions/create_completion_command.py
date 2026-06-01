import logging
import time
import uuid
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.commands.completions.schema_to_model import schema_to_model
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.inference import AgentRunner, build_model
from app.repositories.mcp_tool_catalog_repository import MCPToolCatalogRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository
from app.schemas.completion import CompletionCreate, CompletionResponse
from app.services.mcp.mcp_toolset import MCPToolset
from app.services.mcp.tool_executor import MCPToolExecutor
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
)
from app.infra.logging_config import get_logger

logger = get_logger()


class CreateCompletionCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ModelConfigRepository(db)

    async def execute(
        self,
        payload: CompletionCreate,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ) -> CompletionResponse:
        config = self._resolve_config(payload.model)

        result_model: Optional[type] = None
        if config.output_schema:
            result_model = schema_to_model(config.output_schema)

        tools = await MCPToolCatalogRepository(self.db).get_tools_for_model_config(
            config.id, user_id=user_id
        )

        model = build_model(config, project_id, request_id, user_id=user_id)

        system_prompt_content = None
        if config.system_prompt_id is not None:
            system_prompt_content = SystemPromptRepository(
                self.db
            ).get_current_content_by_id(config.system_prompt_id)

        messages, user_prompt = _split_messages(payload.messages)

        toolsets = None
        if tools:
            executor = MCPToolExecutor(self.db)
            toolsets = [MCPToolset(tools, executor, user_id=user_id)]

        result = await AgentRunner(model).run(
            user_prompt,
            system_prompt=system_prompt_content,
            output_type=result_model,
            message_history=messages or None,
            toolsets=toolsets,
            max_result_retries=config.max_tool_rounds,
        )

        return CompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            object="chat.completion",
            created=int(time.time()),
            model=config.slug,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result.output},
                    "finish_reason": "stop",
                }
            ],
            usage={
                "prompt_tokens": result.input_tokens,
                "completion_tokens": result.output_tokens,
                "total_tokens": result.input_tokens + result.output_tokens,
            },
        )

    async def stream_execute(
        self,
        payload: CompletionCreate,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ):
        config = self._resolve_config(payload.model)

        if config.output_schema:
            raise HTTPException(
                status_code=422,
                detail="Streaming and structured outputs cannot be used together.",
            )

        tools = await MCPToolCatalogRepository(self.db).get_tools_for_model_config(
            config.id, user_id=user_id
        )

        model = build_model(config, project_id, request_id, user_id=user_id)

        system_prompt_content = None
        if config.system_prompt_id is not None:
            system_prompt_content = SystemPromptRepository(
                self.db
            ).get_current_content_by_id(config.system_prompt_id)

        messages, user_prompt = _split_messages(payload.messages)

        toolsets = None
        if tools:
            executor = MCPToolExecutor(self.db)
            toolsets = [MCPToolset(tools, executor, user_id=user_id)]

        return config.slug, AgentRunner(model).run_stream(
            user_prompt,
            system_prompt=system_prompt_content,
            message_history=messages or None,
            toolsets=toolsets,
        )

    def _resolve_config(self, model_slug):
        if model_slug:
            config = self.repo.get_by_slug(model_slug)
            logger.info(f"Resolved config for model {model_slug}: {config}")
            if config is None:
                raise ResourceNotFoundError(f"ModelConfig '{model_slug}' not found")
            return config
        config = self.repo.get_default()
        logger.info(f"Resolved config for model: {config}")
        if config is None:
            raise ResourceNotFoundError("No default ModelConfig is configured")
        return config


def _split_messages(messages):
    """Split OpenAI messages into pydantic-ai history + final user prompt."""
    history = []
    for msg in messages[:-1]:
        if msg.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        elif msg.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    return history, messages[-1].content
