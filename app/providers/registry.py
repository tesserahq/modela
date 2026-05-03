from app.providers.base import BaseProviderAdapter
from app.providers.openai_adapter import OpenAIProviderAdapter

PROVIDER_REGISTRY: dict[str, BaseProviderAdapter] = {
    "openai": OpenAIProviderAdapter(),
}


def get_adapter(provider: str) -> BaseProviderAdapter:
    adapter = PROVIDER_REGISTRY.get(provider)
    if adapter is None:
        raise ValueError(f"Unsupported provider: '{provider}'")
    return adapter
