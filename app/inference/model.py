import time
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.settings import ModelSettings
from app.models.model_config import ModelConfig
from app.tasks.log_completion_usage import log_completion_usage


class ModelaModel(Model):
    """pydantic-ai Model wrapper that applies ModelConfig params and logs usage."""

    _provider = None  # type: ignore[assignment]

    def __init__(
        self,
        inner: Model,
        model_config: ModelConfig,
        project_id: str,
        request_id: str,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._model_config = model_config
        self._project_id = project_id
        self._request_id = request_id

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
        start = time.monotonic()
        response = await self._inner.request(
            messages, effective_settings, model_request_parameters
        )
        latency_ms = int((time.monotonic() - start) * 1000)

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
            cost_estimate_usd=0.0,
        )

        return response


def _apply_config_params(
    config: ModelConfig, model_settings: ModelSettings | None
) -> ModelSettings:
    settings: dict = dict(model_settings or {})
    if config.temperature is not None:
        settings["temperature"] = config.temperature
    if config.max_tokens is not None:
        settings["max_tokens"] = config.max_tokens
    if config.top_p is not None:
        settings["top_p"] = config.top_p
    return settings  # type: ignore[return-value]
