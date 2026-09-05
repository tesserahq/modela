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

    def create_embeddings(
        self, model_name: str, texts: list[str], api_key: str | None = None
    ) -> list[list[float]]:
        """Return one embedding vector per input text, in order. Synchronous, like
        create_model(). Resolves its own key from settings when api_key is None.
        Providers without an embeddings API (e.g. Anthropic) don't need to override
        this — the default raises NotImplementedError."""
        raise NotImplementedError(f"{self.provider_id} does not support embeddings")
