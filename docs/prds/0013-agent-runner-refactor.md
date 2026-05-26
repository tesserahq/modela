# 0013 — AgentRunner: Consolidated pydantic-ai Agent Construction

## Problem Statement

Every command that performs model inference must repeat a four-step boilerplate sequence: build the tracked model wrapper, branch on whether structured output is needed to construct the right `Agent` variant, run the agent with a manually-assembled kwargs dict, and catch pydantic-ai's `UnexpectedModelBehavior` to translate it into the application's own error types. This pattern is currently duplicated across the completion and summarize commands, and will continue to spread to every new inference command added to the codebase.

The duplication means error translation can be forgotten in new commands, the `Agent` construction branch (with vs. without `output_type`) must be replicated correctly each time, and callers are coupled directly to pydantic-ai internals (`RunResult`, `usage()`, `model_dump()`). As the billing/pricing feature approaches, callers also need consistent access to token counts — which is today scattered and inconsistently extracted.

## Solution

Introduce an `AgentRunner` class in the inference layer that owns the full lifecycle of a single agent run: building the `Agent` with the correct configuration, running it, translating exceptions, normalizing the output, and exposing token counts. Commands become thin callers that assemble their domain inputs and delegate execution to `AgentRunner`, receiving a clean `AgentResult` back.

A companion `AgentResult` dataclass exposes the normalized output and token counts, decoupling all callers from pydantic-ai's `RunResult` API.

## User Stories

1. As a backend developer adding a new inference command, I want a single, well-defined entry point for running a model, so that I don't have to remember the correct `Agent` construction pattern or exception-handling boilerplate.
2. As a backend developer, I want `UnexpectedModelBehavior` to always be translated into the application's own error types, so that no command can accidentally surface a raw pydantic-ai exception to the HTTP layer.
3. As a backend developer, I want token counts returned directly from the agent run result, so that I don't have to call `result.usage()` and branch on its fields in every command.
4. As a backend developer, I want structured output (schema-validated JSON) and plain-text output to be handled uniformly, so that I don't have to write `result.output.model_dump() if result_model else result.output` in every completion-style command.
5. As a backend developer, I want to pass a system prompt as a plain string, so that I don't have to know whether to inject it via `Agent(system_prompt=...)` or by prepending a `SystemPromptPart` into message history.
6. As a backend developer, I want optional run parameters (toolsets, message history, max retries) to have safe defaults, so that simple use cases require no extra configuration.
7. As a billing engineer, I want every agent run to return `input_tokens` and `output_tokens` in a consistent location, so that I can wire cost estimation into the response path without touching each command individually.
8. As a backend developer, I want to add a new pydantic-ai `Agent` kwarg (e.g., a new retry policy or model setting) in one place, so that all commands pick it up without individual changes.
9. As a backend developer writing tests, I want to test commands without constructing a real pydantic-ai `Agent`, so that I can mock at the `AgentRunner` boundary instead of deep inside pydantic-ai internals.
10. As a backend developer, I want the completion command to remain responsible for assembling MCP toolsets and message history, so that `AgentRunner` stays free of database and session concerns.
11. As a backend developer, I want the summarize command's default system prompt logic to remain in the summarize command, so that `AgentRunner` has no knowledge of summarization-specific defaults.
12. As a backend developer, I want `AgentRunner` to live in the inference module, so that it is co-located with the model factory and provider adapters it depends on.
13. As a backend developer, I want `AgentResult.output` to always be a `str` or `dict`, so that I never have to check the runtime type before using the result.
14. As a backend developer, I want the existing completion and summarize commands refactored to use `AgentRunner`, so that the old pattern is eliminated and not just supplemented.

## Implementation Decisions

### New: `AgentResult` dataclass

A plain dataclass with three fields:

- `output` — the normalized result of the agent run: a `str` for plain-text outputs, a `dict` (from `model_dump()`) for structured outputs. Callers never call `model_dump()` themselves.
- `input_tokens` — integer token count from the run's usage, defaulting to `0` if unavailable.
- `output_tokens` — integer token count from the run's usage, defaulting to `0` if unavailable.

### New: `AgentRunner` class

Lives in the inference layer. Constructed with a `ModelaModel` instance (the already-wrapped, usage-tracking model). Exposes a single async method:

```
run(
    user_prompt: str | list,
    *,
    system_prompt: str | None = None,
    output_type: type | None = None,
    message_history: list[ModelMessage] = [],
    toolsets: list[AbstractToolset] = [],
    max_result_retries: int | None = None,
) -> AgentResult
```

Internally, `run()`:
1. Constructs the `Agent` — with `output_type` if provided, without it otherwise. The `Agent` is constructed fresh per `run()` call.
2. Prepends system prompt into message history when `system_prompt` is provided (consistent injection strategy for all callers).
3. Assembles the `agent.run()` kwargs dict, omitting `toolsets` and `max_result_retries` entirely when they are absent/None rather than passing falsy values.
4. Catches `UnexpectedModelBehavior`: raises `StructuredOutputValidationError` when `output_type` was set, `ProviderError` otherwise.
5. Normalizes output: calls `model_dump()` when `output_type` was set, returns `result.output` directly for plain text.
6. Extracts token counts from `result.usage()` and returns them in `AgentResult`.

### Modified: `CreateCompletionCommand`

Replaces the manual `Agent` construction, `run_kwargs` assembly, `except UnexpectedModelBehavior` block, and output normalization with a single `AgentRunner(model).run(...)` call. The command retains responsibility for: resolving `ModelConfig`, building `result_model` from the output schema, fetching MCP tools, resolving system prompt content, and splitting message history.

### Modified: `CreateSummarizeCommand`

Replaces `Agent(model=model, system_prompt=...)`, `agent.run(user_prompt)`, and `except UnexpectedModelBehavior` with `AgentRunner(model).run(user_prompt, system_prompt=...)`. The command retains responsibility for: resolving `ModelConfig`, choosing the default system prompt, and constructing the `SummarizeResponse`.

### Exports

`AgentRunner` and `AgentResult` are exported from the inference module's public `__init__` alongside the existing `build_model`, `ModelaModel`, and adapter exports.

### No changes to `ModelaModel`, `build_model`, or provider adapters

`AgentRunner` wraps a `ModelaModel` — it does not replace it. Usage logging, latency measurement, and config-param application remain in `ModelaModel.request()` as before.

### System prompt injection strategy

Both callers currently use different mechanisms (completion prepends via `message_history`, summarize passes to `Agent` constructor). `AgentRunner` standardizes on a single approach. The chosen approach should be consistent with pydantic-ai's documented behavior for the providers in use (Anthropic and OpenAI).

## Testing Decisions

Good tests for this refactor test external behavior at the command boundary — they assert on what the HTTP response contains (output text, token counts, error codes), not on how `AgentRunner` or `Agent` is constructed internally.

**`AgentRunner` unit tests** — test the class in isolation with a mock `ModelaModel`. Cover:
- Plain text output returned correctly in `AgentResult.output`
- Structured output (`output_type` set) returned as `dict` via `model_dump()`
- `UnexpectedModelBehavior` with `output_type` → `StructuredOutputValidationError`
- `UnexpectedModelBehavior` without `output_type` → `ProviderError`
- Token counts populated in `AgentResult`
- System prompt injection (verify the assembled message history contains the prompt)

Prior art: `tests/routers/` — existing integration tests use the real DB session with transaction rollback and override `get_current_user`. Unit tests for `AgentRunner` can use `pytest-asyncio` and `unittest.mock.AsyncMock` for the `ModelaModel`.

**Existing command integration tests** — must pass without modification after the refactor. No new assertions needed; their continued passage confirms behavioral equivalence.

**No tests for internal branching inside `AgentRunner`** — do not write tests that assert `Agent` was constructed with specific kwargs. Test outcomes, not construction.

## Out of Scope

- Streaming support (`agent.run_stream()`) — `AgentRunner` handles non-streaming requests only. A future `run_stream()` method can be added when needed.
- Cost estimation — `AgentResult` exposes token counts but does not compute `cost_estimate_usd`. That belongs to the billing/pricing feature (see PRD-0007).
- New inference commands — this PRD covers only the two existing commands. Future commands should use `AgentRunner` from the start.
- Changes to `ModelaModel`, provider adapters, or the Celery usage-logging task.
- Changes to HTTP response schemas — `CompletionResponse` and `SummarizeResponse` shapes are unchanged.

## Further Notes

The immediate motivation for this refactor is the upcoming billing/pricing feature. Consistent token count exposure via `AgentResult` is a prerequisite for wiring cost estimates into the response path without touching each command individually.

The system prompt injection strategy decision (message-history prepend vs. `Agent` constructor) should be validated against pydantic-ai's behavior with both Anthropic and OpenAI providers before implementation, since the two providers may handle system prompt placement differently.
