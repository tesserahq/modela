import time
import uuid
from uuid import UUID

from fastapi import HTTPException
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from sqlalchemy.orm import Session

from app.commands.completions.schema_to_model import schema_to_model
from app.exceptions.completion_run_error import CompletionRunError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.inference import AgentRunner, build_model
from app.infra.logging_config import get_logger
from app.repositories.mcp_tool_catalog_repository import MCPToolCatalogRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository
from app.schemas.completion import CompletionCreate, CompletionResponse
from app.services.mcp.event_collector import CompletionEventCollector
from app.services.mcp.mcp_toolset import MCPToolset
from app.services.mcp.tool_executor import MCPToolExecutor
from app.services.tools.builtin_toolset import build_builtin_toolset

logger = get_logger()


class CreateCompletionCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ModelConfigRepository(db)
        # Extension channels the caller requested but the resolved ModelConfig
        # does not expose; the router reports them in a response header.
        self.omitted_includes: list[str] = []

    async def execute(
        self,
        payload: CompletionCreate,
        project_id: str,
        request_id: str,
        *,
        user_id: UUID,
    ) -> CompletionResponse:
        config = self._resolve_config(payload.model)
        event_collector = self._event_collector_for(payload, config)

        result_model: type | None = None
        if config.output_schema:
            result_model = schema_to_model(config.output_schema)

        tools = await MCPToolCatalogRepository(self.db).get_tools_for_model_config(
            config.id, user_id=user_id
        )

        model = build_model(config, project_id, request_id, user_id=user_id)

        config_system_prompt = None
        if config.system_prompt_id is not None:
            config_system_prompt = SystemPromptRepository(
                self.db
            ).get_current_content_by_id(config.system_prompt_id)

        caller_system_prompts, messages, user_prompt = _split_messages(payload.messages)
        system_prompt_content = _merge_system_prompts(
            config_system_prompt, caller_system_prompts
        )

        toolsets = self._build_toolsets(config, tools, user_id, event_collector)

        try:
            result = await AgentRunner(model).run(
                user_prompt,
                system_prompt=system_prompt_content,
                output_type=result_model,
                message_history=messages or None,
                toolsets=toolsets,
                max_result_retries=config.max_tool_rounds,
            )
        except Exception as error:
            if event_collector is None:
                raise
            raise CompletionRunError(
                error,
                events=event_collector.events,
                truncations=event_collector.truncations,
            ) from error

        # `extensions` is passed only when requested, so it stays unset (and is
        # omitted from the response) for callers that did not opt in.
        extensions = self._response_extensions(event_collector)
        return CompletionResponse(
            **extensions,
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
        event_collector = self._event_collector_for(payload, config)

        tools = await MCPToolCatalogRepository(self.db).get_tools_for_model_config(
            config.id, user_id=user_id
        )

        model = build_model(config, project_id, request_id, user_id=user_id)

        config_system_prompt = None
        if config.system_prompt_id is not None:
            config_system_prompt = SystemPromptRepository(
                self.db
            ).get_current_content_by_id(config.system_prompt_id)

        caller_system_prompts, messages, user_prompt = _split_messages(payload.messages)
        system_prompt_content = _merge_system_prompts(
            config_system_prompt, caller_system_prompts
        )

        toolsets = self._build_toolsets(config, tools, user_id, event_collector)

        return config.slug, AgentRunner(model).run_stream(
            user_prompt,
            system_prompt=system_prompt_content,
            message_history=messages or None,
            toolsets=toolsets,
            drain_events=event_collector.drain if event_collector else None,
            drain_event_truncation=(
                event_collector.drain_truncation if event_collector else None
            ),
        )

    @staticmethod
    def _response_extensions(
        event_collector: CompletionEventCollector | None,
    ) -> dict:
        if event_collector is None:
            return {}
        extension_values = {"events": event_collector.events}
        truncations = event_collector.truncations
        if truncations:
            extension_values["truncations"] = truncations
        return {"extensions": extension_values}

    def _event_collector_for(self, payload, config) -> CompletionEventCollector | None:
        """Return a collector when the `events` channel is requested and exposed.

        A request for events on a ModelConfig that does not expose them still
        completes normally: the channel is omitted (never returned as an empty
        list, which would mean "no events happened") and recorded in
        ``omitted_includes`` so the caller can tell it was not delivered.
        """
        if not payload.wants_events:
            return None
        if not config.expose_events:
            logger.info(
                "Omitting 'events' channel: ModelConfig %s does not expose it",
                config.slug,
            )
            self.omitted_includes.append("events")
            return None
        return CompletionEventCollector()

    def _build_toolsets(self, config, mcp_tools, user_id, event_collector=None):
        """Combines the MCP-server toolset (existing, per-server tools) with
        the built-in toolset (config.enabled_tools) into one list, or None if
        neither has anything to contribute — mirrors the pre-existing
        `toolsets = None unless truthy` contract AgentRunner.run()/run_stream()
        rely on."""
        toolsets = []
        if mcp_tools:
            executor = MCPToolExecutor(self.db)
            toolsets.append(
                MCPToolset(
                    mcp_tools,
                    executor,
                    user_id=user_id,
                    event_collector=event_collector,
                )
            )
        builtin_toolset = build_builtin_toolset(self.db, config.enabled_tools)
        if builtin_toolset is not None:
            toolsets.append(builtin_toolset)
        return toolsets or None

    def _resolve_config(self, model_slug):
        if model_slug:
            config = self.repo.get_by_slug(model_slug)
            if config is None:
                raise ResourceNotFoundError(f"ModelConfig '{model_slug}' not found")
            if config.config_type != "chat":
                raise HTTPException(
                    status_code=422,
                    detail=f"ModelConfig '{model_slug}' is not a chat config "
                    f"(config_type='{config.config_type}')",
                )
            return config
        config = self.repo.get_default_for_type("chat")
        if config is None:
            raise ResourceNotFoundError("No default chat ModelConfig is configured")
        return config


def _split_messages(messages):
    """Split OpenAI messages into caller system prompts, pydantic-ai history
    and the final user prompt.

    System messages are collected separately (wherever they appear) so they
    can be merged with the model config's own system prompt instead of being
    silently dropped.
    """
    system_prompts = []
    history = []
    for msg in messages[:-1]:
        if msg.role == "system":
            if msg.content:
                system_prompts.append(msg.content)
        elif msg.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        elif msg.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    return system_prompts, history, messages[-1].content


def _merge_system_prompts(config_system_prompt, caller_system_prompts):
    """Config prompt first (operator-level instructions), then the caller's
    system messages in request order. Returns None when there is nothing."""
    parts = [p for p in [config_system_prompt, *caller_system_prompts] if p]
    if not parts:
        return None
    return "\n\n".join(parts)
