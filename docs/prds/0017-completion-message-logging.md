## Problem Statement

When a consumer calls `POST /chat/completions`, Modela logs token counts, cost, latency, and provider/model metadata for every request in `completion_requests` — but not the actual content of the conversation. If a customer reports a bad or unexpected response, there is no way to see what was actually sent to the model or what the model actually said back. There is also no way to analyze real usage patterns (what kinds of prompts are being sent, what responses look like) or produce an audit trail of what customers sent through the API.

## Solution

Persist the request's input messages and the model's response text on each `completion_requests` row, using the same asynchronous logging pipeline that already records token usage and cost. No new endpoints or API-facing behavior change — this is purely an internal logging enhancement. `messages` and `response` are stored as plain (unencrypted) columns, nullable so existing rows are unaffected. This PRD covers the `/chat/completions` endpoint only, for both non-streaming and streaming (`stream=true`) requests; the summarize endpoint is explicitly out of scope.

## User Stories

1. As a developer supporting a customer issue, I want to see the exact messages sent to the model for a given `completion_requests` row, so that I can reproduce and debug a bad response.
2. As a developer supporting a customer issue, I want to see the model's response text for a given `completion_requests` row, so that I don't have to ask the customer to resend logs.
3. As a compliance/audit stakeholder, I want an immutable record of what was sent through the API and what came back, so that I can investigate disputes or incidents after the fact.
4. As a product analyst, I want access to historical prompt and response content, so that I can analyze usage patterns and inform product decisions.
5. As an API consumer using streaming responses, I want my request logged the same way as non-streaming requests, so that debugging and audit coverage isn't weaker for streaming traffic.
6. As an API consumer whose request triggers multiple tool-use rounds, I want each logged row to be self-contained, so that any single row can be inspected without needing to correlate across rows.
7. As an operator running the database, I want existing `completion_requests` rows to remain valid after this change, so that no backfill or migration risk is introduced.
8. As a developer maintaining `CreateSummarizeCommand` (or other future `build_model()` callers), I want the new message-logging parameter to be optional and default to inactive, so that unrelated commands aren't forced to adopt OpenAI-style message logging.

## Implementation Decisions

- **Schema:** Add two nullable columns to `CompletionRequest`: `messages` (JSONB — array of `{role, content}` objects) and `response` (TEXT — the model's response text). Both default to `NULL`. Generated via `alembic revision --autogenerate`; no backfill for historical rows.
- **Data protection:** Stored as plain columns, no encryption, consistent with the rest of `completion_requests`. Not run through a redaction or PII-scrubbing step. Flagged as a follow-up conversation for whoever owns audit/compliance requirements, not solved in this PRD.
- **Capture source:** The `messages` column stores the raw `payload.messages` submitted by the API consumer (the OpenAI-style request body), not pydantic-ai's internal `ModelMessage` history (which would include system prompt and tool-call scaffolding).
- **Plumbing:** `log_completion_usage.delay()` is invoked from inside `ModelaModel.request()` / `ModelaModel.request_stream()` (`app/inference/model.py`), which is the single shared logging chokepoint also used by other commands via `build_model()`. `messages` is threaded through as a new optional parameter: `CreateCompletionCommand` → `build_model()` → `ModelaModel.__init__` → included in the `.delay()` call. The parameter defaults to `None` when omitted.
- **Response text — non-streaming:** In `ModelaModel.request()`, extract text from the `response: ModelResponse` object already in scope (its `TextPart`s), and pass it to `log_completion_usage.delay()` as `response_text`.
- **Response text — streaming:** In `ModelaModel.request_stream()`, after the `async with self._inner.request_stream(...) as stream:` block exits (stream is fully consumed by that point), call `stream.get()` to obtain the accumulated `ModelResponse`, and extract text the same way as the non-streaming path.
- **Shared extraction logic:** The `TextPart`-joining logic used by both `request()` and `request_stream()` should live in one small helper function rather than being duplicated, so it can be unit tested independently of Celery/DB.
- **Multi-turn tool calls:** No dedup logic. If an API request triggers multiple LLM rounds (tool use), `ModelaModel.request()` fires once per round, and each resulting `completion_requests` row (sharing the same `request_id`) stores the same original `payload.messages`, with its own round-specific `response`. This matches existing behavior for token/latency logging and keeps each row self-contained.
- **Serialization for Celery:** `payload.messages` (a list of `MessageInput` pydantic objects) is serialized via `.model_dump()` before being passed into `.delay()`, since Celery task arguments must be JSON-serializable.
- **Scope boundary — summarize:** `CreateSummarizeCommand` also calls `build_model()`, but its `user_prompt` is not in OpenAI message format (it can be a plain string or a list containing `ImageUrl`/`DocumentUrl` parts for file summarization). This PRD does not attempt to reshape that into `messages`. `CreateSummarizeCommand` continues calling `build_model()` without the `messages` argument, so summarize-originated `completion_requests` rows keep `messages = NULL`.
- **Schema/repository updates:** `CompletionRequestCreate` and `CompletionRequestResponse` (in `app/schemas/completion_request.py`) gain optional `messages` and `response` fields. `CompletionRequestRepository.create()` requires no logic change since it already does `CompletionRequest(**data.model_dump())`.
- **Task signature:** `log_completion_usage` (`app/tasks/log_completion_usage.py`) gains `messages: Optional[list] = None` and `response_text: Optional[str] = None` keyword arguments, forwarded into `CompletionRequestCreate`.

## Testing Decisions

Good tests here exercise externally observable behavior — what ends up in the `completion_requests` row or what a helper function returns given a message object — not internal call sequencing.

- **Text-extraction helper:** Unit test the `TextPart`-joining helper directly with fabricated `ModelResponse` objects (multiple `TextPart`s, a `TextPart` mixed with a tool-call part, empty parts list) to confirm it joins/filters correctly. No DB or Celery required. This is the one piece of new logic worth testing in isolation.
- **`log_completion_usage` task:** Extend `tests/app/tasks/test_log_completion_usage.py` (existing pattern already covers this task) to assert that `messages` and `response_text` passed into the task are persisted onto the resulting `CompletionRequest` row via `CompletionRequestRepository`.
- **Router/integration test:** Extend `tests/routers/test_completion_router.py` and `tests/routers/test_completion_streaming.py` (existing patterns already cover `/chat/completions` for both modes) to assert that after calling the endpoint, the corresponding `completion_requests` row has `messages` populated with the submitted messages and `response` populated with non-empty text, for both the non-streaming and streaming cases.
- No new test files are anticipated beyond extending these three existing suites, aside from the helper unit test.

## Out of Scope

- Encryption or redaction of message/response content at rest.
- Message logging for the summarize endpoint (`CreateSummarizeCommand`) or any other non-chat command using `build_model()`.
- Deduplication of `messages` across multiple tool-use rounds sharing the same `request_id`.
- Backfilling `messages`/`response` for historical `completion_requests` rows.
- Exposing `messages`/`response` through any new or existing API response (this PRD only covers persistence, not surfacing the data via `CompletionRequestResponse` consumers, dashboards, or exports).
- Retention policy / TTL for stored message content.

## Further Notes

- If audit/compliance requirements later demand encryption or redaction, the `messages`/`response` columns can be revisited without a schema change (values would simply be encrypted before insert / decrypted on read), but that decision should go through a dedicated security review rather than being folded into this PRD.
- If summarize-endpoint logging is wanted later, it will need its own decision on how to represent a non-chat `user_prompt` (string or file-content parts) as a `messages`-shaped payload.
