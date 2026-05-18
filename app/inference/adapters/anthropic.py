from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from app.config import get_settings
from app.inference.adapters.base import BaseProviderAdapter


class AnthropicProviderAdapter(BaseProviderAdapter):
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
