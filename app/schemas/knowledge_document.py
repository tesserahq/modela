from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_RAW_CONTENT_BYTES = 1_048_576  # 1 MiB, per PRD 0019


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(..., max_length=255)
    raw_content: str = Field(..., max_length=MAX_RAW_CONTENT_BYTES)


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    raw_content: str | None = Field(None, max_length=MAX_RAW_CONTENT_BYTES)


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    content: str
    metadata: dict[str, Any] | None = Field(None, validation_alias="extended_info")
    created_at: datetime
    updated_at: datetime
