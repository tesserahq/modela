from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.inference.adapters.registry import get_adapter

EMBEDDING_CHUNK_STRATEGIES = {"fixed_size"}


class EmbeddingConfigParams(BaseModel):
    chunk_size: int = Field(..., ge=256, le=8192)
    chunk_overlap: int = Field(..., ge=0)
    strategy: str

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, value: str) -> str:
        if value not in EMBEDDING_CHUNK_STRATEGIES:
            raise ValueError(
                f"strategy must be one of {sorted(EMBEDDING_CHUNK_STRATEGIES)}, got '{value}'"
            )
        return value

    @model_validator(mode="after")
    def _validate_overlap(self) -> "EmbeddingConfigParams":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size")
        return self


def validate_embedding_config_params(
    config_type: str, params: dict[str, Any] | None
) -> None:
    """Validate `ModelConfig.params` for config_type="embedding". No-op for other types."""
    if config_type != "embedding":
        return
    if params is None:
        raise InvalidParameterError(
            "params (chunk_size, chunk_overlap, strategy) is required for config_type='embedding'"
        )
    try:
        EmbeddingConfigParams.model_validate(params)
    except ValidationError as exc:
        raise InvalidParameterError(f"Invalid embedding config params: {exc}")


def validate_embedding_model_choice(
    config_type: str, provider: str, model: str
) -> None:
    """Validate that `model` is in `provider`'s embedding catalog for
    config_type="embedding". No-op for other config types and for unknown
    providers (parameter validation elsewhere already tolerates those)."""
    if config_type != "embedding":
        return
    try:
        adapter = get_adapter(provider)
    except ValueError:
        return
    valid_ids = {m.id for m in adapter.list_embedding_models()}
    if model not in valid_ids:
        raise InvalidParameterError(
            f"'{model}' is not a supported embedding model for provider '{provider}'"
        )
