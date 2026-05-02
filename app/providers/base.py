from abc import ABC, abstractmethod
from pydantic_ai.models import Model


class BaseProviderAdapter(ABC):
    @abstractmethod
    def create_model(self, model_name: str, api_key: str | None = None) -> Model:
        """Return a pydantic-ai Model. Resolves its own key from settings when api_key is None."""
        raise NotImplementedError
