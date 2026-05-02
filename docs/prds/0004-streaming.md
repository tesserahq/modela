# PRD 0004 — Streaming

## Overview

This phase adds Server-Sent Events (SSE) streaming to the `/chat/completions` endpoint. When `stream: true` is set in the request, Modela proxies the provider's token stream to the caller using an OpenAI-compatible chunked response format. All three providers (OpenAI, Anthropic, Ollama) gain streaming support.

---

## Goals

- Support `stream: true` on `POST /chat/completions`
- Return OpenAI-compatible SSE chunks (`data: {...}\n\n` format)
- Implement streaming for OpenAI, Anthropic, and Ollama adapters
- Accumulate token usage from the stream for usage logging
- Keep the non-streaming path entirely unchanged

---

## Non-Goals

- Streaming structured outputs (complex to validate mid-stream; deferred)
- WebSocket-based streaming (SSE is sufficient and simpler)
- Client-side reconnect / resumable streams
- Per-chunk latency metrics (aggregate latency only in this phase)

---

## Background

Streaming is essential for user-facing applications where response latency matters — displaying tokens as they arrive rather than waiting for the full completion. The OpenAI SSE format is the de-facto standard and is what most client SDKs (including the OpenAI Python SDK) expect.

The key architectural challenge is that FastAPI's `StreamingResponse` must remain open while the provider connection is active. Usage logging cannot happen until the stream is complete, so it is deferred to stream close.

---

## API Changes

### `POST /chat/completions` — streaming request

```json
{
  "model": "openai-gpt-4o",
  "messages": [{ "role": "user", "content": "Tell me a story." }],
  "stream": true
}
```

When `stream: true`:

- Response `Content-Type` is `text/event-stream`
- Response body is a sequence of SSE events in OpenAI chunk format

### SSE Chunk Format

Each chunk is an OpenAI-compatible `ChatCompletionChunk` object:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"openai-gpt-4o","choices":[{"index":0,"delta":{"role":"assistant","content":"Once"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"openai-gpt-4o","choices":[{"index":0,"delta":{"content":" upon"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"openai-gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

The `model` field in chunks reflects the ModelConfig slug (not the provider-native model name), consistent with the non-streaming response.

### Non-streaming unchanged

If `stream` is absent or `false`, the existing non-streaming path is used without modification.

---

## Adapter Interface Extension

`BaseProviderAdapter` gains a streaming method alongside the existing `complete`:

```python
class BaseProviderAdapter(ABC):
    @abstractmethod
    async def complete(
        self,
        config: ModelConfig,
        messages: list[Message],
        extra_body: dict | None,
    ) -> CompletionResponse:
        ...

    @abstractmethod
    async def stream(
        self,
        config: ModelConfig,
        messages: list[Message],
        extra_body: dict | None,
    ) -> AsyncIterator[StreamChunk]:
        ...
```

**`StreamChunk`** internal type:

```python
@dataclass
class StreamChunk:
    id: str
    content_delta: str | None   # None on the final chunk
    finish_reason: str | None   # set on the final chunk
    input_tokens: int | None    # set on the final chunk (from usage event)
    output_tokens: int | None   # set on the final chunk
```

The endpoint layer converts `StreamChunk` → OpenAI SSE chunk JSON.

---

## Provider Implementations

### OpenAI

Uses the SDK's native async streaming:

```python
async with client.chat.completions.stream(...) as stream:
    async for chunk in stream:
        yield StreamChunk(...)
    usage = stream.get_final_completion().usage
```

### Anthropic

Uses the Anthropic SDK's `stream()` context manager:

```python
async with client.messages.stream(...) as stream:
    async for text in stream.text_stream:
        yield StreamChunk(content_delta=text, ...)
    final = await stream.get_final_message()
    # emit final chunk with usage
```

### Ollama

Ollama's OpenAI-compatible endpoint supports streaming natively. The Ollama adapter reuses the OpenAI streaming implementation with its custom `base_url`, identical to the non-streaming case.

---

## Usage Logging for Streaming Requests

Token counts are only available at stream end (in the final provider event). The usage logging Celery task is enqueued after the final `StreamChunk` is yielded and the SSE connection closes — not at the start of the stream.

If the client disconnects before the stream completes:

- The provider connection is closed immediately (generator cleanup via `aclose()`)
- A partial usage record is written with `finish_reason: "client_disconnected"` and whatever token counts are available

---

## Structured Outputs + Streaming

`output_schema` and `stream: true` are mutually exclusive in this phase. If both are present in the request (or the ModelConfig has an `output_schema` and `stream: true` is set), Modela returns:

```json
{
  "error": "IncompatibleOptions",
  "message": "Streaming and structured outputs cannot be used together."
}
```

HTTP status: `422`.

---

## Error Handling

Mid-stream errors (provider disconnects, rate limits during stream) are emitted as a final SSE error event before closing:

```
data: {"error": {"type": "ProviderStreamError", "message": "Provider disconnected mid-stream."}}

data: [DONE]
```

The HTTP status remains `200` (SSE convention — status is sent with headers before streaming begins). Clients must inspect the event payload for errors.

---

## Dependencies

- PRD 0001 (BaseProviderAdapter, ModelConfig, usage logging)
- PRD 0003 (Anthropic and Ollama adapters exist)

---

## Success Criteria

- `stream: true` returns a valid SSE response with OpenAI-compatible chunks
- All three providers (OpenAI, Anthropic, Ollama) stream correctly
- Usage is logged after stream completion with accurate token counts
- Client disconnection closes the provider connection and writes a partial usage record
- `stream: true` + `output_schema` returns a `422` error
- Non-streaming requests are completely unaffected
- All new streaming paths have integration tests

---

## Amendment — PRD 0008 Interaction

**`stream: true` + agentic tool loop is not supported in this phase.** When PRD 0008 ships, if a request has `stream: true` and tools are available (via the MCP registry), Modela returns `422 IncompatibleOptions`. Full streaming of agentic loops — emitting token deltas mid-loop across multiple tool-call rounds — requires a coordinated design across SSE, pydantic-ai's streaming interface, and multi-round tool execution. That work is deferred until both PRD 0004 and PRD 0008 are stable in production.

---

## Testing

**SSE response format**
- `stream: true` returns `Content-Type: text/event-stream`
- Chunks are valid OpenAI `ChatCompletionChunk` JSON
- Final chunk has `finish_reason` set; all prior chunks have `finish_reason: null`
- Stream ends with `data: [DONE]`

**Usage logging**
- `llm_calls` row is written after stream completes with correct token counts
- Partial usage row is written with `finish_reason: "client_disconnected"` when client disconnects mid-stream

**Incompatible combinations**
- `stream: true` + `output_schema` returns `422 IncompatibleOptions`
- `stream: true` + non-empty `tools` field returns `422 IncompatibleOptions` (PRD 0008)

**Non-streaming regression**
- Requests without `stream` or with `stream: false` return a standard (non-SSE) response unchanged
