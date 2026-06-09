from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from app.config import get_settings
from app.inference.adapters.base import BaseProviderAdapter
from app.schemas.provider import ParameterSpec, ProviderModelSchema, ProviderParameters


class OpenAIProviderAdapter(BaseProviderAdapter):
    provider_id = "openai"
    provider_name = "OpenAI"
    parameters = ProviderParameters(
        temperature=ParameterSpec(default=1.0, min=0.0, max=2.0),
        top_p=ParameterSpec(default=1.0, min=0.0, max=1.0),
    )

    _models = [
        ProviderModelSchema(id="gpt-4.1", name="GPT-4.1"),
        ProviderModelSchema(id="gpt-4.1-mini", name="GPT-4.1 Mini"),
        ProviderModelSchema(id="gpt-4.1-nano", name="GPT-4.1 Nano"),
        ProviderModelSchema(id="gpt-4o", name="GPT-4o"),
        ProviderModelSchema(id="gpt-4o-mini", name="GPT-4o Mini"),
        ProviderModelSchema(id="o3", name="o3"),
        ProviderModelSchema(id="o4-mini", name="o4 Mini"),
    ]

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

    def list_models(self) -> list[ProviderModelSchema]:
        return self._models
