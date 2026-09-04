from abc import ABC, abstractmethod

from pydantic_ai.models import Model

from app.schemas.provider import (
    LiveProviderModel,
    ProviderModelSchema,
    ProviderParameters,
)


class BaseProviderAdapter(ABC):
    provider_id: str
    provider_name: str
    parameters: ProviderParameters | None = None
    # Id prefixes that identify this provider's chat-completion model family
    # (e.g. ("claude",) or ("gpt", "o")). Used to filter noise — other model
    # types the provider lists (embeddings, audio, moderation, ...) — out of
    # the live catalog drift check. Not used by list_models()/create_model().
    model_id_prefixes: tuple[str, ...] = ()

    @abstractmethod
    def create_model(self, model_name: str, api_key: str | None = None) -> Model:
        """Return a pydantic-ai Model. Resolves its own key from settings when api_key is None."""
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[ProviderModelSchema]:
        """Return the curated list of available models for this provider."""
        raise NotImplementedError

    @abstractmethod
    def fetch_live_model_ids(self) -> list[LiveProviderModel]:
        """Fetch the provider's current live model list, for catalog drift detection only."""
        raise NotImplementedError
