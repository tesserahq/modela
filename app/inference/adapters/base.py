from abc import ABC, abstractmethod
from pydantic_ai.models import Model
from app.schemas.provider import ProviderModelSchema


class BaseProviderAdapter(ABC):
    provider_id: str
    provider_name: str

    @abstractmethod
    def create_model(self, model_name: str, api_key: str | None = None) -> Model:
        """Return a pydantic-ai Model. Resolves its own key from settings when api_key is None."""
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[ProviderModelSchema]:
        """Return the curated list of available models for this provider."""
        raise NotImplementedError
