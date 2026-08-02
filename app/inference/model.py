import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from uuid import UUID

from opentelemetry import trace
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.settings import ModelSettings
from app.inference.adapters.parameter_validation import (
    clamp_model_config_parameter,
    resolve_provider_settings,
)
from app.infra.telemetry import safe_instrument_span
from app.models.model_config import ModelConfig
from app.tasks.log_completion_usage import log_completion_usage

tracer = trace.get_tracer(__name__)


class ModelaModel(Model):
    """pydantic-ai Model wrapper that applies ModelConfig params and logs usage."""

    _provider = None  # type: ignore[assignment]

    def __init__(
        self,
        inner: Model,
        model_config: ModelConfig,
        project_id: str,
        request_id: str,
        *,
        user_id: Optional[UUID] = None,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._model_config = model_config
        self._project_id = project_id
        self._request_id = request_id
        self._user_id = user_id
        self._request_attempt = 0

    def _next_request_attempt(self) -> int:
        self._request_attempt += 1
        return self._request_attempt

    def _span_attributes(self, attempt: int, *, streamed: bool) -> dict[str, object]:
        return {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": self._model_config.provider,
            "gen_ai.request.model": self._model_config.model,
            "modela.model_config.slug": self._model_config.slug,
            "modela.request.attempt": attempt,
            "modela.request.streamed": streamed,
        }

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @property
    def system(self) -> str:
        return self._inner.system

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._inner.__aexit__(exc_type, exc_val, exc_tb)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        effective_settings = _apply_config_params(self._model_config, model_settings)
        attempt = self._next_request_attempt()
        with safe_instrument_span(
            tracer,
            "inference.model.request",
            attributes=self._span_attributes(attempt, streamed=False),
        ) as span:
            start = time.monotonic()
            response = await self._inner.request(
                messages, effective_settings, model_request_parameters
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            span.set_attribute(
                "gen_ai.usage.input_tokens", response.usage.input_tokens or 0
            )
            span.set_attribute(
                "gen_ai.usage.output_tokens", response.usage.output_tokens or 0
            )
            span.set_attribute("modela.provider.latency_ms", latency_ms)

        log_completion_usage.delay(
            request_id=self._request_id,
            project_id=self._project_id,
            model_config_slug=self._model_config.slug,
            provider=self._model_config.provider,
            model=self._model_config.model,
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
            finish_reason=None,
            latency_ms=latency_ms,
            created_by_id=str(self._user_id) if self._user_id else None,
        )

        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context=None,
    ) -> AsyncIterator[StreamedResponse]:
        effective_settings = _apply_config_params(self._model_config, model_settings)
        attempt = self._next_request_attempt()
        with safe_instrument_span(
            tracer,
            "inference.model.request",
            attributes=self._span_attributes(attempt, streamed=True),
        ) as span:
            start = time.monotonic()
            async with self._inner.request_stream(
                messages,
                effective_settings,
                model_request_parameters,
                run_context,
            ) as stream:
                yield stream
            latency_ms = int((time.monotonic() - start) * 1000)
            usage = stream.usage()
            span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens or 0)
            span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens or 0)
            span.set_attribute("modela.provider.latency_ms", latency_ms)
        log_completion_usage.delay(
            request_id=self._request_id,
            project_id=self._project_id,
            model_config_slug=self._model_config.slug,
            provider=self._model_config.provider,
            model=self._model_config.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            finish_reason=None,
            latency_ms=latency_ms,
            created_by_id=str(self._user_id) if self._user_id else None,
        )


def _apply_config_params(
    config: ModelConfig, model_settings: ModelSettings | None
) -> ModelSettings:
    settings: dict = dict(model_settings or {})
    if config.temperature is not None:
        settings["temperature"] = clamp_model_config_parameter(
            config.provider, "temperature", config.temperature
        )
    if config.max_tokens is not None:
        settings["max_tokens"] = clamp_model_config_parameter(
            config.provider, "max_tokens", config.max_tokens
        )
    if config.top_p is not None:
        settings["top_p"] = clamp_model_config_parameter(
            config.provider, "top_p", config.top_p
        )
    return resolve_provider_settings(config.provider, settings)  # type: ignore[return-value]
