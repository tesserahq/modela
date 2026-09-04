from datetime import UTC, datetime

import httpx
from openai import OpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import get_settings
from app.inference.adapters.base import BaseProviderAdapter
from app.schemas.provider import (
    LiveProviderModel,
    ParameterSpec,
    ProviderModelSchema,
    ProviderParameters,
)

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"


class OpenAIProviderAdapter(BaseProviderAdapter):
    provider_id = "openai"
    provider_name = "OpenAI"
    # OpenAI's /v1/models also lists embeddings, whisper, tts, moderation,
    # dall-e, etc. — these prefixes scope the catalog check to chat models.
    model_id_prefixes = ("gpt", "o")
    parameters = ProviderParameters(
        temperature=ParameterSpec(default=1.0, min=0.0, max=2.0),
        top_p=ParameterSpec(default=1.0, min=0.0, max=1.0),
    )

    # Grouped by family (4.1, 4o, o-series). When adding a new model, insert
    # it into its family group rather than appending to the end, so the
    # model picker stays grouped.
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

    def create_embeddings(
        self, model_name: str, texts: list[str], api_key: str | None = None
    ) -> list[list[float]]:
        key = api_key if api_key is not None else get_settings().openai_api_key
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=key)
        response = client.embeddings.create(model=model_name, input=texts)
        return [item.embedding for item in response.data]

    def list_models(self) -> list[ProviderModelSchema]:
        return self._models

    def fetch_live_model_ids(self) -> list[LiveProviderModel]:
        key = get_settings().openai_api_key
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured")

        response = httpx.get(
            OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            LiveProviderModel(
                id=item["id"],
                created_at=datetime.fromtimestamp(item["created"], tz=UTC),
            )
            for item in payload.get("data", [])
        ]
