import httpx
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.config import get_settings
from app.inference.adapters.base import BaseProviderAdapter
from app.schemas.provider import (
    LiveProviderModel,
    ParameterSpec,
    ProviderModelSchema,
    ProviderParameters,
)

ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProviderAdapter(BaseProviderAdapter):
    provider_id = "anthropic"
    provider_name = "Anthropic"
    model_id_prefixes = ("claude",)
    parameters = ProviderParameters(
        temperature=ParameterSpec(default=1.0, min=0.0, max=1.0),
        top_p=ParameterSpec(min=0.0, max=1.0),
        exclusive_parameter_groups=[["temperature", "top_p"]],
    )

    _models = [
        ProviderModelSchema(
            id="claude-fable-5-1",
            name="Claude Fable 5.1",
            description="Best for creative and long-form writing, storytelling, and open-ended content generation.",
        ),
        ProviderModelSchema(
            id="claude-opus-5",
            name="Claude Opus 5",
            description="Most capable model, best for complex reasoning, agentic tasks, and hard coding problems.",
        ),
        ProviderModelSchema(
            id="claude-sonnet-5",
            name="Claude Sonnet 5",
            description="Balanced default, strong performance at lower cost and latency than Opus.",
        ),
        ProviderModelSchema(
            id="claude-fable-5",
            name="Claude Fable 5",
            description="Best for creative and long-form writing, storytelling, and open-ended content generation.",
        ),
        ProviderModelSchema(
            id="claude-opus-4-8",
            name="Claude Opus 4.8",
            description="Most capable model, best for complex reasoning, agentic tasks, and hard coding problems.",
        ),
        ProviderModelSchema(
            id="claude-opus-4-7",
            name="Claude Opus 4.7",
            description="Most capable model, best for complex reasoning, agentic tasks, and hard coding problems.",
        ),
        ProviderModelSchema(
            id="claude-sonnet-4-6",
            name="Claude Sonnet 4.6",
            description="Balanced default, strong performance at lower cost and latency than Opus.",
        ),
        ProviderModelSchema(
            id="claude-opus-4-6",
            name="Claude Opus 4.6",
            description="Most capable model, best for complex reasoning, agentic tasks, and hard coding problems.",
        ),
        ProviderModelSchema(
            id="claude-opus-4-5-20251101",
            name="Claude Opus 4.5",
            description="Most capable model, best for complex reasoning, agentic tasks, and hard coding problems.",
        ),
        ProviderModelSchema(
            id="claude-haiku-4-5-20251001",
            name="Claude Haiku 4.5",
            description="Fastest and cheapest, best for high-volume, latency-sensitive tasks.",
        ),
        ProviderModelSchema(
            id="claude-sonnet-4-5-20250929",
            name="Claude Sonnet 4.5",
            description="Balanced default, strong performance at lower cost and latency than Opus.",
        ),
    ]

    def create_model(
        self, model_name: str, api_key: str | None = None
    ) -> AnthropicModel:
        key = api_key if api_key is not None else get_settings().anthropic_api_key
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return AnthropicModel(
            model_name,
            provider=AnthropicProvider(api_key=key),
        )

    def list_models(self) -> list[ProviderModelSchema]:
        return self._models

    def fetch_live_model_ids(self) -> list[LiveProviderModel]:
        key = get_settings().anthropic_api_key
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")

        headers = {"X-Api-Key": key, "anthropic-version": ANTHROPIC_API_VERSION}
        live_models: list[LiveProviderModel] = []
        after_id: str | None = None

        while True:
            params = {"after_id": after_id} if after_id else {}
            response = httpx.get(
                ANTHROPIC_MODELS_URL, headers=headers, params=params, timeout=10.0
            )
            response.raise_for_status()
            payload = response.json()
            live_models.extend(
                LiveProviderModel(id=item["id"], created_at=item["created_at"])
                for item in payload.get("data", [])
            )
            if not payload.get("has_more"):
                break
            after_id = payload.get("last_id")

        return live_models
