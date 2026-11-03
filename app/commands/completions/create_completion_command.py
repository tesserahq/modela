import time
import uuid
from functools import partial
from uuid import UUID

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from app.commands.completions.schema_to_model import schema_to_model
from app.commands.load_model_config import load_model_config
from app.db import SessionFactory
from app.exceptions.completion_run_error import CompletionRunError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.inference import AgentRunner, build_model
from app.infra.logging_config import get_logger
from app.repositories.mcp_tool_catalog_repository import MCPToolCatalogRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.completion import (
    CompletionCreate,
    CompletionResponse,
    build_event_extensions,
)
from app.services.mcp.event_collector import CompletionEventCollector
from app.services.mcp.mcp_toolset import MCPToolset
from app.services.mcp.tool_executor import MCPToolExecutor
from app.services.tools.builtin_toolset import build_builtin_toolset

logger = get_logger()


class CreateCompletionCommand:
    """Runs a chat completion without holding a database connection.

    The config, system prompt and MCP servers load in short sessions in the
    threadpool before the model runs; tool calls open their own (linden-api
    SDD 0012). A streamed run therefore holds no connection while it streams.
    """

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions
        self._tool_catalog = MCPToolCatalogRepository(sessions)
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
        config, config_system_prompt = await self._load_config(payload.model)
        event_collector = self._event_collector_for(payload, config)

        result_model: type | None = None
        if config.output_schema:
            result_model = schema_to_model(config.output_schema)

        tools = await self._tool_catalog.get_tools_for_model_config(
            config.id, user_id=user_id
        )

        model = build_model(config, project_id, request_id, user_id=user_id)

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
        config, config_system_prompt = await self._load_config(payload.model)

        if config.output_schema:
            raise HTTPException(
                status_code=422,
                detail="Streaming and structured outputs cannot be used together.",
            )
        event_collector = self._event_collector_for(payload, config)

        tools = await self._tool_catalog.get_tools_for_model_config(
            config.id, user_id=user_id
        )

        model = build_model(config, project_id, request_id, user_id=user_id)

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
            event_truncation=(event_collector.truncation if event_collector else None),
        )

    @staticmethod
    def _response_extensions(
        event_collector: CompletionEventCollector | None,
    ) -> dict:
        if event_collector is None:
            return {}
        return {
            "extensions": build_event_extensions(
                event_collector.events, event_collector.truncations
            )
        }

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
            executor = MCPToolExecutor(self._sessions)
            toolsets.append(
                MCPToolset(
                    mcp_tools,
                    executor,
                    user_id=user_id,
                    event_collector=event_collector,
                )
            )
        builtin_toolset = build_builtin_toolset(self._sessions, config.enabled_tools)
        if builtin_toolset is not None:
            toolsets.append(builtin_toolset)
        return toolsets or None

    async def _load_config(self, model_slug):
        return await run_in_threadpool(
            load_model_config,
            self._sessions,
            partial(self._resolve_config, model_slug=model_slug),
        )

    @staticmethod
    def _resolve_config(repo: ModelConfigRepository, model_slug):
        if model_slug:
            config = repo.get_by_slug(model_slug)
            if config is None:
                raise ResourceNotFoundError(f"ModelConfig '{model_slug}' not found")
            if config.config_type != "chat":
                raise HTTPException(
                    status_code=422,
                    detail=f"ModelConfig '{model_slug}' is not a chat config "
                    f"(config_type='{config.config_type}')",
                )
            return config
        config = repo.get_default_for_type("chat")
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
