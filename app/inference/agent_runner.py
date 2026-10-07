from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx
from opentelemetry import trace
from pydantic_ai import Agent
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    PartDeltaEvent,
    PartStartEvent,
    SystemPromptPart,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.toolsets import AbstractToolset

from app.exceptions.provider_errors import ProviderError, ProviderTimeoutError
from app.exceptions.structured_output_validation_error import (
    StructuredOutputValidationError,
)
from app.inference.model import ModelaModel
from app.infra.logging_config import get_logger
from app.infra.telemetry import safe_instrument_span

logger = get_logger()
tracer = trace.get_tracer(__name__)

_PROVIDER_TIMEOUT_STATUSES = frozenset({408, 504})


def _classify_provider_error(error: ModelAPIError) -> ProviderError:
    """Map a failed provider request to the provider error the API reports.

    pydantic-ai wraps SDK failures in ModelAPIError; an SDK timeout (e.g.
    openai.APITimeoutError) is chained from the transport's
    httpx.TimeoutException, so the cause chain identifies it without
    importing each provider SDK.
    """
    if isinstance(error, ModelHTTPError):
        if error.status_code in _PROVIDER_TIMEOUT_STATUSES:
            return ProviderTimeoutError(str(error))
        return ProviderError(str(error))
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, (httpx.TimeoutException, TimeoutError)):
            return ProviderTimeoutError(str(error))
        cause = cause.__cause__
    return ProviderError(str(error))


@dataclass
class AgentResult:
    output: (
        Any  # str for plain text, dict for structured output (already model_dump()'d)
    )
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class StreamedExtension:
    """Typed extension item rendered by the transport's generic envelope."""

    payload: dict[str, Any]
    field: ClassVar[str]

    def __post_init__(self) -> None:
        # The transport reads `field` after the response has started, so a
        # missing one must fail here rather than mid-stream.
        if not isinstance(getattr(type(self), "field", None), str):
            raise TypeError(f"{type(self).__name__} must define a `field` name")


@dataclass(frozen=True)
class StreamedEvent(StreamedExtension):
    """A serialized domain event to interleave with streamed text."""

    field = "event"


@dataclass(frozen=True)
class StreamedTruncation(StreamedExtension):
    """A terminal response-channel truncation marker."""

    field = "truncation"


def _terminal_event_items(
    drain_events: Callable[[], list[dict[str, Any]]] | None,
    event_truncation: Callable[[], dict[str, Any] | None] | None,
) -> list[StreamedEvent | StreamedTruncation]:
    """Drain final events, then the channel's truncation marker if any.

    Called exactly once per stream, so the marker is emitted at most once.
    """
    items: list[StreamedEvent | StreamedTruncation] = []
    if drain_events is not None:
        items.extend(StreamedEvent(payload) for payload in drain_events())
    if event_truncation is not None:
        marker = event_truncation()
        if marker is not None:
            items.append(StreamedTruncation(marker))
    return items


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

        span_attributes: dict[str, object] = {
            "modela.inference.structured_output": output_type is not None,
            "modela.inference.message_history.count": len(history),
            "modela.inference.toolset.count": len(toolsets or []),
        }
        if max_result_retries is not None:
            span_attributes["modela.inference.max_result_retries"] = max_result_retries

        with safe_instrument_span(
            tracer, "inference.agent.run", attributes=span_attributes
        ):
            try:
                result = await agent.run(user_prompt, **run_kwargs)
            except ModelAPIError as e:
                raise _classify_provider_error(e) from e
            except UnexpectedModelBehavior as e:
                if output_type is not None:
                    raise StructuredOutputValidationError(
                        "Provider response did not conform to the requested schema.",
                        validation_errors=[{"message": str(e)}],
                        raw_content=str(e),
                    )
                raise ProviderError(str(e)) from e

        usage = result.usage()
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
        drain_events: Callable[[], list[dict[str, Any]]] | None = None,
        event_truncation: Callable[[], dict[str, Any] | None] | None = None,
    ) -> AsyncIterator[str | StreamedEvent | StreamedTruncation]:
        """Stream text deltas, interleaved with domain events when requested.

        ``drain_events`` returns events recorded since its previous call. It is
        polled after every agent event, so an event is yielded right after the
        tool result that produced it, in actual execution order.

        ``event_truncation`` returns the events channel's truncation marker, or
        None. It is read once, after the final drain on success or failure, so
        its ``dropped_count`` is complete and the marker follows the last
        retained event.
        """
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

        span_attributes: dict[str, object] = {
            "modela.inference.structured_output": False,
            "modela.inference.message_history.count": len(history),
            "modela.inference.toolset.count": len(toolsets or []),
        }
        if max_result_retries is not None:
            span_attributes["modela.inference.max_result_retries"] = max_result_retries

        with safe_instrument_span(
            tracer, "inference.agent.run", attributes=span_attributes
        ):
            try:
                async with agent.run_stream_events(user_prompt, **run_kwargs) as events:
                    async for event in events:
                        if drain_events is not None:
                            for payload in drain_events():
                                yield StreamedEvent(payload)
                        if isinstance(event, PartStartEvent) and isinstance(
                            event.part, TextPart
                        ):
                            if event.part.content:
                                yield event.part.content
                        elif (
                            isinstance(event, PartDeltaEvent)
                            and isinstance(event.delta, TextPartDelta)
                            and event.delta.content_delta
                        ):
                            yield event.delta.content_delta
            except Exception:
                # A tool may have committed a mutation immediately before a
                # later model/provider failure. Give the transport one chance
                # to send those events before propagating the original error.
                try:
                    items = _terminal_event_items(drain_events, event_truncation)
                except Exception:
                    # Never let the drain mask the provider error being raised.
                    logger.exception("Failed to drain completion events after error")
                    items = []
                for item in items:
                    yield item
                raise
            for item in _terminal_event_items(drain_events, event_truncation):
                yield item
