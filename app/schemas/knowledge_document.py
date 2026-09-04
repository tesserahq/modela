from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_RAW_CONTENT_BYTES = 1_048_576  # 1 MiB, per PRD 0019


def _validate_raw_content_bytes(value: str | None) -> str | None:
    if value is not None and len(value.encode("utf-8")) > MAX_RAW_CONTENT_BYTES:
        raise ValueError("raw_content must not exceed 1 MiB when UTF-8 encoded")
    return value


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(..., max_length=255)
    raw_content: str

    _raw_content_within_byte_limit = field_validator("raw_content")(
        _validate_raw_content_bytes
    )


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    raw_content: str | None = None

    _raw_content_within_byte_limit = field_validator("raw_content")(
        _validate_raw_content_bytes
    )


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    content: str
    metadata: dict[str, Any] | None = Field(None, validation_alias="extended_info")
    created_at: datetime
    updated_at: datetime
