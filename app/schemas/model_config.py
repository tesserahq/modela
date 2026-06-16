from pydantic import BaseModel, Field
from typing import Literal, Optional, Any
from uuid import UUID
from datetime import datetime
from app.schemas.system_prompt import SystemPromptCompact

ConfigType = Literal["chat", "summary", "generation", "scan"]

_CONFIG_TYPE_META: dict[str, tuple[str, str]] = {
    "chat": ("Chat", "General-purpose conversational completions."),
    "summary": ("Summary", "Summarizes documents or text content into concise output."),
    "generation": ("Generation", "Generates text or structured content from a prompt."),
    "scan": ("Scan", "Extracts structured data from uploaded documents or images."),
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
    system_prompt_id: Optional[UUID] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    output_schema: Optional[dict[str, Any]] = None
    config_type: ConfigType = "chat"
    is_default: bool = False
    max_tool_rounds: Optional[int] = Field(None, ge=1, le=50)


class ModelConfigCreate(ModelConfigBase):
    pass


class ModelConfigUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=255)
    name: Optional[str] = Field(None, max_length=255)
    provider: Optional[str] = Field(None, max_length=100)
    model: Optional[str] = Field(None, max_length=255)
    system_prompt_id: Optional[UUID] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    output_schema: Optional[dict[str, Any]] = None
    config_type: Optional[ConfigType] = None
    is_default: Optional[bool] = None
    max_tool_rounds: Optional[int] = Field(None, ge=1, le=50)


class ModelConfigResponse(ModelConfigBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    system_prompt: Optional[SystemPromptCompact] = None

    model_config = {"from_attributes": True}
