import logging
import time
import uuid
from sqlalchemy.orm import Session
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.gateway.modela_model import ModelaModel
from app.providers.registry import get_adapter
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository
from app.schemas.completion import CompletionCreate, CompletionResponse

logger = logging.getLogger(__name__)


class CreateCompletionCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ModelConfigRepository(db)

    async def execute(
        self, payload: CompletionCreate, project_id: str, request_id: str
    ) -> CompletionResponse:
        config = self._resolve_config(payload.model)

        adapter = get_adapter(config.provider)
        inner = adapter.create_model(config.model)
        model = ModelaModel(inner, config, project_id, request_id)

        system_prompt_content = None
        if config.system_prompt_id is not None:
            system_prompt_content = SystemPromptRepository(
                self.db
            ).get_current_content_by_id(config.system_prompt_id)
        agent: Agent[None, str] = Agent(model=model, instructions=system_prompt_content)

        messages, user_prompt = _split_messages(payload.messages)

        result = await agent.run(user_prompt, message_history=messages)

        usage = result.usage()
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
                "prompt_tokens": usage.input_tokens,
                "completion_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
            },
        )

    def _resolve_config(self, model_slug):
        if model_slug:
            config = self.repo.get_by_slug(model_slug)
            if config is None:
                raise ResourceNotFoundError(f"ModelConfig '{model_slug}' not found")
            return config
        config = self.repo.get_default()
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
