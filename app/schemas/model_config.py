from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.system_prompt import SystemPromptCompact

ConfigType = Literal["chat", "summary", "generation", "scan", "embedding"]

_CONFIG_TYPE_META: dict[str, tuple[str, str]] = {
    "chat": ("Chat", "General-purpose conversational completions."),
    "summary": ("Summary", "Summarizes documents or text content into concise output."),
    "generation": ("Generation", "Generates text or structured content from a prompt."),
    "scan": ("Scan", "Extracts structured data from uploaded documents or images."),
    "embedding": (
        "Embedding",
        (
            "Produces vector embeddings for the knowledge base. Warning: changing "
            "the provider or model on an embedding config that already produced "
            "chunk embeddings invalidates them (dimension/provenance mismatch) — "
            "create a new embedding config instead of mutating one already in use."
        ),
    ),
}


class ConfigTypeRead(BaseModel):
    id: str
    name: str
    description: str

    @classmethod
    def from_id(cls, config_type_id: str) -> "ConfigTypeRead":
        name, description = _CONFIG_TYPE_META[config_type_id]
        return cls(id=config_type_id, name=name, description=description)


class MCPServerAttachRequest(BaseModel):
    server_id: UUID


class ModelConfigBase(BaseModel):
    slug: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    provider: str = Field(..., max_length=100)
    model: str = Field(..., max_length=255)
    system_prompt_id: UUID | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, gt=0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)
    output_schema: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    config_type: ConfigType = "chat"
    is_default: bool = False
    max_tool_rounds: int | None = Field(None, ge=1, le=50)
    enabled_tools: list[str] | None = None


class ModelConfigCreate(ModelConfigBase):
    pass


class ModelConfigUpdate(BaseModel):
    slug: str | None = Field(None, max_length=255)
    name: str | None = Field(None, max_length=255)
    provider: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=255)
    system_prompt_id: UUID | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, gt=0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)
    output_schema: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    config_type: ConfigType | None = None
    is_default: bool | None = None
    max_tool_rounds: int | None = Field(None, ge=1, le=50)
    enabled_tools: list[str] | None = None


class ModelConfigResponse(ModelConfigBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    system_prompt: SystemPromptCompact | None = None

    model_config = {"from_attributes": True}
