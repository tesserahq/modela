from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from app.config import get_settings
from app.inference.adapters.base import BaseProviderAdapter
from app.schemas.provider import ProviderModelSchema


class AnthropicProviderAdapter(BaseProviderAdapter):
    provider_id = "anthropic"
    provider_name = "Anthropic"

    _models = [
        ProviderModelSchema(id="claude-opus-4-5", name="Claude Opus 4.5"),
        ProviderModelSchema(id="claude-sonnet-4-6", name="Claude Sonnet 4.6"),
        ProviderModelSchema(id="claude-sonnet-4-5", name="Claude Sonnet 4.5"),
        ProviderModelSchema(id="claude-haiku-4-5", name="Claude Haiku 4.5"),
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
