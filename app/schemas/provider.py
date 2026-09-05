from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LiveProviderModel(BaseModel):
    """A model id as currently reported by a provider's live models endpoint."""

    id: str
    created_at: datetime


class ParameterSpec(BaseModel):
    default: float | int | None = None
    min: float | None = None
    max: float | None = None


class ProviderParameters(BaseModel):
    temperature: ParameterSpec | None = None
    top_p: ParameterSpec | None = None
    max_tokens: ParameterSpec | None = None
    exclusive_parameter_groups: list[list[str]] | None = None


class ProviderModelSchema(BaseModel):
    id: str
    name: str
    description: str | None = None
    # Real $/million-token rates from genai_prices, populated at request time.
    # Null when the model isn't in genai_prices' dataset yet (e.g. a very
    # recently released id).
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None


class ProviderSchema(BaseModel):
    id: str
    name: str
    models: list[ProviderModelSchema]
    embedding_models: list[ProviderModelSchema] = []
    parameters: ProviderParameters | None = None


class ProviderCatalogCheckResponse(BaseModel):
    """Response schema for POST /providers/check-catalog."""

    task_id: str
    status: str = "queued"
