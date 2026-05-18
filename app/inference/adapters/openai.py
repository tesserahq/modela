from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from app.config import get_settings
from app.inference.adapters.base import BaseProviderAdapter


class OpenAIProviderAdapter(BaseProviderAdapter):
    def create_model(
        self, model_name: str, api_key: str | None = None
    ) -> OpenAIChatModel:
        key = api_key if api_key is not None else get_settings().openai_api_key
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured")
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(api_key=key),
        )
