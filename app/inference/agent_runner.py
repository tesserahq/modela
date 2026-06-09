from dataclasses import dataclass
from typing import Any, AsyncIterator

from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart
from pydantic_ai.toolsets import AbstractToolset

from app.exceptions.provider_errors import ProviderError
from app.exceptions.structured_output_validation_error import (
    StructuredOutputValidationError,
)
from app.inference.model import ModelaModel


@dataclass
class AgentResult:
    output: (
        Any  # str for plain text, dict for structured output (already model_dump()'d)
    )
    input_tokens: int
    output_tokens: int


class AgentRunner:
    def __init__(self, model: ModelaModel) -> None:
        self._model = model

    async def run(
        self,
        user_prompt: str | list,
        *,
        system_prompt: str | None = None,
        output_type: type | None = None,
        message_history: list[ModelMessage] | None = None,
        toolsets: list[AbstractToolset] | None = None,
        max_result_retries: int | None = None,
    ) -> AgentResult:
        if output_type is not None:
            agent: Agent = Agent(model=self._model, output_type=output_type)
        else:
            agent = Agent(model=self._model)

        history: list[ModelMessage] = list(message_history) if message_history else []
        if system_prompt is not None:
            history = [
                ModelRequest(parts=[SystemPromptPart(content=system_prompt)])
            ] + history

        run_kwargs: dict = {}
        if history:
            run_kwargs["message_history"] = history
        if toolsets:
            run_kwargs["toolsets"] = toolsets
        if max_result_retries is not None:
            run_kwargs["output_retries"] = max_result_retries

        try:
            result = await agent.run(user_prompt, **run_kwargs)
        except UnexpectedModelBehavior as e:
            if output_type is not None:
                raise StructuredOutputValidationError(
                    "Provider response did not conform to the requested schema.",
                    validation_errors=[{"message": str(e)}],
                    raw_content=str(e),
                )
            raise ProviderError(str(e)) from e

        usage = result.usage
        return AgentResult(
            output=(
                result.output.model_dump() if output_type is not None else result.output
            ),
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
        )

    async def run_stream(
        self,
        user_prompt: str | list,
        *,
        system_prompt: str | None = None,
        message_history: list[ModelMessage] | None = None,
        toolsets: list[AbstractToolset] | None = None,
        max_result_retries: int | None = None,
    ) -> AsyncIterator[str]:
        agent = Agent(model=self._model)

        history: list[ModelMessage] = list(message_history) if message_history else []
        if system_prompt is not None:
            history = [
                ModelRequest(parts=[SystemPromptPart(content=system_prompt)])
            ] + history

        run_kwargs: dict = {}
        if history:
            run_kwargs["message_history"] = history
        if toolsets:
            run_kwargs["toolsets"] = toolsets
        if max_result_retries is not None:
            run_kwargs["output_retries"] = max_result_retries

        async with agent.run_stream(user_prompt, **run_kwargs) as result:
            async for delta in result.stream_text(delta=True):
                yield delta
