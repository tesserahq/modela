from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator
from tessera_sdk.clients.modela import ChatCompletionExtensions
from tessera_sdk.mcp import CompletionInclude

# Response channels this service can currently deliver. `tool_executions` is
# part of the shared contract but is rejected until diagnostics ship (#106).
SUPPORTED_INCLUDES = frozenset({CompletionInclude.EVENTS})


class MessageInput(BaseModel):
    role: str
    content: str


class CompletionCreate(BaseModel):
    model: Optional[str] = None
    messages: list[MessageInput] = Field(min_length=1)
    stream: bool = False
    include: Optional[list[CompletionInclude]] = None
    # tessera-sdk's ModelaClient sends `extra_body` as a literal nested key, so
    # `extra_body.include` is accepted as an alias for top-level `include`.
    extra_body: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def merge_include_sources(self):
        nested = (self.extra_body or {}).get("include")
        if nested is not None:
            if not isinstance(nested, list):
                raise ValueError("extra_body.include must be a list")
            try:
                nested_values = [CompletionInclude(value) for value in nested]
            except ValueError:
                raise ValueError(
                    "extra_body.include contains an unsupported value"
                ) from None
            if self.include is not None and set(self.include) != set(nested_values):
                raise ValueError("include conflicts with extra_body.include")
            self.include = self.include if self.include is not None else nested_values

        unsupported = set(self.include or ()) - SUPPORTED_INCLUDES
        if unsupported:
            names = ", ".join(sorted(value.value for value in unsupported))
            raise ValueError(f"Unsupported include value(s): {names}")
        return self

    @property
    def wants_events(self) -> bool:
        return CompletionInclude.EVENTS in (self.include or ())


class CompletionChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class CompletionChunkChoice(BaseModel):
    index: int
    delta: CompletionChunkDelta
    finish_reason: Optional[str] = None


class CompletionChunk(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: list[CompletionChunkChoice]


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
    # Present only when the caller requested an extension channel; the route
    # serializes with exclude_unset so default responses are unchanged.
    extensions: Optional[ChatCompletionExtensions] = None
