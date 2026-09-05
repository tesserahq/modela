# PRD 0016 — Streaming via pydantic-ai

> **Supersedes PRD 0004.** PRD 0004 was designed for a now-replaced adapter architecture. This PRD re-specifies streaming for the current pydantic-ai / AgentRunner stack introduced in PRD 0013.

---

## Problem Statement

The `/chat/completions` endpoint returns a complete response only after the entire model output has been generated. For user-facing applications, this means the caller must wait — sometimes several seconds — before receiving any tokens. There is no way to display tokens incrementally, which makes Modela unsuitable as a backend for chat interfaces that expect real-time output.

## Solution

Add a `stream` flag to the `/chat/completions` request body. When `stream: true`, the endpoint returns a `text/event-stream` response that emits tokens as they arrive from the provider, following the OpenAI SSE chunk format. The non-streaming path is unchanged. All ModelConfig parameters (temperature, max_tokens, top_p), MCP tool execution, and usage logging apply equally to streaming requests.

---

## User Stories

1. As a chat application developer, I want to receive tokens incrementally from `/chat/completions`, so that I can display them to the user in real time without waiting for the full response.
2. As a chat application developer, I want to set `"stream": true` in my existing request body, so that I don't have to change the endpoint URL or learn a new API.
3. As a chat application developer, I want the SSE response format to match OpenAI's `ChatCompletionChunk` schema, so that I can reuse existing OpenAI client SDKs and parsing code.
4. As a chat application developer, I want the stream to end with `data: [DONE]`, so that I know unambiguously when to close the connection.
5. As a chat application developer, I want each SSE chunk to include a stable `id` field shared across all chunks in a response, so that I can correlate chunks to a single completion request.
6. As a chat application developer, I want the `model` field in SSE chunks to reflect the ModelConfig slug, so that I know which named config was used — not the provider's internal model name.
7. As a chat application developer, I want streaming requests that include message history to work identically to non-streaming requests, so that I can build stateless multi-turn chat on top of streaming.
8. As a chat application developer, I want `stream: false` (or omitting the field) to return the existing non-streaming response unchanged, so that I can migrate incrementally.
9. As a backend developer, I want streaming requests to apply ModelConfig parameters (temperature, max_tokens, top_p) identically to non-streaming requests, so that behavior is consistent regardless of `stream`.
10. As a backend developer, I want streaming requests to execute MCP tool calls transparently, so that tool-augmented ModelConfigs work without any extra configuration.
11. As a backend developer, I want usage (input/output token counts) to be logged to the database after the stream completes, so that billing and analytics remain accurate for streaming requests.
12. As a backend developer, I want the `X-Modela-Request-Id` and `X-Modela-Config-Slug` response headers to be present on streaming responses, so that callers can correlate and trace requests regardless of stream mode.
13. As a backend developer, I want a `422` error if `stream: true` is requested on a ModelConfig that has `output_schema` set, so that the incompatibility is surfaced clearly rather than silently producing malformed output.
14. As a backend developer, I want `AgentRunner` to expose a `run_stream()` method alongside the existing `run()`, so that streaming is a first-class path in the inference layer rather than a special case in the router.
15. As a backend developer, I want `ModelaModel` to implement `request_stream()` so that pydantic-ai's `Agent.run_stream()` can use it, so that streaming passes through the same config-param application and usage-logging wrapper as non-streaming requests.
16. As a backend developer writing tests, I want to verify that `stream: true` + `output_schema` returns `422`, so that the incompatibility is covered by the test suite.
17. As a backend developer writing tests, I want to verify the SSE chunk format against the OpenAI spec, so that regressions in chunk structure are caught before they affect clients.

---

## Implementation Decisions

### Schema change: `CompletionCreate`

Add `stream: bool = False` to the existing `CompletionCreate` request schema. No other schema changes are needed for the request.

### New schema: `CompletionChunk`

A new Pydantic schema representing a single OpenAI-compatible SSE chunk. Fields:

- `id` — stable string shared across all chunks in a single completion (e.g. `chatcmpl-{uuid}`)
- `object` — always `"chat.completion.chunk"`
- `created` — Unix timestamp (integer), set once at stream start
- `model` — the ModelConfig slug
- `choices` — list with a single entry containing:
  - `index` — always `0`
  - `delta` — dict with `"role": "assistant"` on the first chunk; `"content": "<token>"` on content chunks; `{}` on the final chunk
  - `finish_reason` — `null` on all chunks except the last, `"stop"` on the last

The SSE wire format for each chunk: `data: {json}\n\n`. The stream ends with `data: [DONE]\n\n`.

### Modified: `ModelaModel`

Implement `request_stream()` as an `@asynccontextmanager` that:

1. Applies ModelConfig params (temperature, max_tokens, top_p) via `_apply_config_params()` — identical to `request()`.
2. Delegates to `self._inner.request_stream(messages, effective_settings, model_request_parameters)` using `async with`.
3. Yields the `StreamedResponse` to the caller.
4. After the caller has exhausted the stream and control returns, reads usage from `stream.usage()` and fires the Celery `log_completion_usage` task — identical to the task call in `request()`.

The method signature matches pydantic-ai's `Model.request_stream()` ABC: `(self, messages, model_settings, model_request_parameters, run_context=None) -> AsyncContextManager[StreamedResponse]`.

### Modified: `AgentRunner`

Add a `run_stream()` async generator method alongside the existing `run()`. It accepts the same parameters as `run()` (minus `output_type`, which is incompatible with streaming — see below). Internally it:

1. Constructs the `Agent` without `output_type` (plain text only).
2. Prepends the system prompt into message history using the same strategy as `run()`.
3. Calls `agent.run_stream()` as an async context manager.
4. Async-iterates over `result.stream_text(delta=True)` to yield individual text deltas as strings.
5. After the stream is exhausted, reads `result.usage()` and returns `(input_tokens, output_tokens)` — the caller is responsible for firing the usage log (or `AgentRunner` can fire it internally; see note below).

**Note on usage logging placement:** `ModelaModel.request_stream()` fires the Celery task after the stream is exhausted (step 4 above). This is consistent with `ModelaModel.request()`. `AgentRunner.run_stream()` does not need to fire usage separately — it happens in the model wrapper.

### Modified: `CreateCompletionCommand`

Add a `stream_execute()` async generator method (or extend `execute()` with a `stream` parameter) that:

1. Performs the same setup as `execute()`: resolves config, detects `output_schema`, fetches MCP tools, builds the model, resolves system prompt.
2. If `output_schema` is set, raises a `422`-mapped error immediately.
3. Calls `AgentRunner(model).run_stream(...)` and yields deltas to the router.

The existing `execute()` method is unchanged.

### Modified: completion router

When `payload.stream is True`:

- Calls `CreateCompletionCommand(db).stream_execute(payload, project_id, request_id, user_id=...)` to get an async generator of text deltas.
- Returns a `StreamingResponse` with `media_type="text/event-stream"`.
- The generator function wraps each delta into an OpenAI `CompletionChunk` JSON, prefixed with `data: ` and suffixed with `\n\n`. The first chunk includes `"role": "assistant"` in `delta`; subsequent chunks have only `"content"`. The final chunk has `"delta": {}` and `"finish_reason": "stop"`. The stream ends with `data: [DONE]\n\n`.
- Sets `X-Modela-Config-Slug` and `X-Modela-Request-Id` headers on the `StreamingResponse`.

When `payload.stream is False` (or absent), the existing non-streaming path runs unchanged.

### Structured output incompatibility

If `stream: true` is set and the resolved ModelConfig has a non-null `output_schema`, the command raises an `UnprocessableEntityError` (HTTP 422) with:

```json
{
  "error": "IncompatibleOptions",
  "message": "Streaming and structured outputs cannot be used together."
}
```

This check happens before the model is built or any provider call is made.

### MCP tools

MCP tool execution is handled through pydantic-ai's `agent.run_stream_events()`,
which keeps the full agent graph running across tool-call rounds. Text emitted by
each model turn is forwarded as SSE chunks, while tool-call and tool-result events
remain internal. No changes are needed to MCP toolset assembly.

### Usage logging

Token counts are extracted from the completed `StreamedRunResult` after the stream is exhausted. The Celery `log_completion_usage` task is fired from within `ModelaModel.request_stream()` after the inner model's stream context manager exits — identical timing to `ModelaModel.request()`. If the caller disconnects before exhausting the stream, the `StreamingResponse` generator will be garbage-collected; the `asynccontextmanager` exit in `ModelaModel.request_stream()` will still run and will log whatever partial usage is available from `stream.usage()` at that point.

### No usage in SSE chunks

Token counts are not included in the SSE response. Callers that need counts query the analytics endpoint.

---

## Testing Decisions

Good tests for streaming assert on observable wire-level behavior: HTTP headers, SSE format, chunk content, and error responses. They do not assert on internal construction of `Agent`, `AgentRunner`, or `ModelaModel`.

**What makes a good test here:** a test is good if it would catch a real regression — a chunk with the wrong `object` field, a missing `[DONE]`, a missing `finish_reason` on the last chunk, or a 422 that isn't raised. Tests that only verify that a mock was called are not valuable.

### Modules to test

**`AgentRunner.run_stream()` unit tests** — test with a mock `ModelaModel` that yields a known sequence of deltas. Assert that deltas are yielded correctly and that the method returns after the stream. Prior art: existing `AgentRunner` tests in `tests/`.

**`CreateCompletionCommand` integration tests (streaming path)** — same test setup as existing completion integration tests (real DB session, `dependency_overrides` for auth, patched pydantic-ai `Agent`). Cover:
- `stream: true` returns `200` with `Content-Type: text/event-stream`
- Response body parses as valid SSE with OpenAI chunk structure
- First chunk contains `"role": "assistant"` in `delta`; subsequent chunks have `"content"` only
- Final chunk has `"finish_reason": "stop"` and `"delta": {}`
- Stream ends with `data: [DONE]`
- `X-Modela-Request-Id` and `X-Modela-Config-Slug` headers are present
- `stream: true` + ModelConfig with `output_schema` returns `422`
- `stream: false` (default) returns the existing non-streaming response unchanged (regression check)

Prior art: `tests/routers/test_completion_router.py` — uses `create_client_fixture`, real DB session, transaction rollback, and `app.dependency_overrides`.

---

## Out of Scope

- Streaming structured outputs (returns 422; may be revisited in a future PRD)
- Usage counts in SSE response body (`stream_options: {include_usage: true}`)
- Client-disconnect partial usage records beyond best-effort (whatever pydantic-ai surfaces at stream close)
- WebSocket-based streaming
- Per-chunk latency metrics
- Streaming the summarize endpoint

---

## Further Notes

This PRD depends on PRD 0013 (AgentRunner) being implemented and stable. The pydantic-ai `Model.request_stream()` ABC raises `NotImplementedError` by default — any provider adapter that the `_inner` model delegates to must implement it. Both OpenAI and Anthropic pydantic-ai model implementations support streaming natively; no changes to provider adapters are required.

The `run_stream()` method uses `agent.run_stream_events()` so the agent graph runs
to completion across tool-call rounds. The simpler `agent.run_stream()` API must
not be used here: it treats the first output matching the configured output type
as final and can stop before executing a tool call that follows leading text.
