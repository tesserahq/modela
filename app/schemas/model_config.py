from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from uuid import UUID
from datetime import datetime


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
    is_default: bool = False


class ModelConfigCreate(ModelConfigBase):
    pass


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    system_prompt_id: Optional[UUID] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    output_schema: Optional[dict[str, Any]] = None
    is_default: Optional[bool] = None


class ModelConfigResponse(ModelConfigBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
