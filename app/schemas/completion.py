from typing import Any, Optional
from pydantic import BaseModel, Field


class MessageInput(BaseModel):
    role: str
    content: str


class CompletionCreate(BaseModel):
    model: Optional[str] = None
    messages: list[MessageInput] = Field(min_length=1)
    extra_body: Optional[dict[str, Any]] = None


class CompletionChoice(BaseModel):
    index: int
    message: dict[str, Any]
    finish_reason: str


class CompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CompletionResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: list[CompletionChoice]
    usage: CompletionUsage
