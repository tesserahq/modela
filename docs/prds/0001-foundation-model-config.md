# PRD 0001 — Foundation & ModelConfig

## Overview

This phase delivers a working end-to-end AI gateway: a single OpenAI-compatible HTTP endpoint that resolves a named **ModelConfig**, forwards the request to OpenAI, and logs usage. It establishes the core abstractions all future phases build on.

---

## Goals

- Introduce **ModelConfig** as the central configuration primitive
- Introduce **`ModelaModel`**: a pydantic-ai `Model` implementation that acts as the gateway interceptor for all LLM calls (usage logging, ModelConfig parameter application, BYOK key resolution)
- Ship a working OpenAI completion (non-streaming) via pydantic-ai's `OpenAIModel`
- Expose an OpenAI-compatible `POST /chat/completions` endpoint
- Log per-request usage (tokens, latency, cost estimate) to Postgres
- Keep platform credentials simple: env-var / config-based API keys

---

## Implementation Decisions

> Decisions captured from design review (2026-05-02).

| #   | Topic                                 | Decision                                                                                                                                                                              |
| --- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `project_id` in `completion_requests` | Taken from the `project_id` query parameter on the request. Defaults to `"*"` if absent. Uses the same `infer_project` resolver pattern as the Eventa router.                         |
| 2   | Completion endpoint RBAC              | Requires `modela.completion:create` with `project_resolver=infer_project`. Same pattern as Eventa: `build_rbac_dependencies(resource="completion", project_resolver=infer_project)`.  |
| 3   | `cost_estimate_usd`                   | Stubbed as `0` in Phase 1. Provider-based pricing will be added in a later phase.                                                                                                     |
| 4   | `extra_body` conflict resolution      | **Config wins.** `extra_body` fields are merged after config parameters, so config-defined values (temperature, max_tokens, top_p) are not overridable by `extra_body`.               |
| 5   | `is_default` enforcement              | **Auto-clear.** When a ModelConfig is created or updated with `is_default: true`, all other rows are automatically set to `is_default: false` at the application layer. No 409 error. |
| 6   | Pagination on list endpoint           | Use `fastapi-pagination` (`Page[T]` response with `items`, `total`, `page`, `size` from query params). Already installed.                                                             |

---

## Non-Goals

- Streaming (PRD 0004)
- Structured output validation (PRD 0002)
- Multiple providers (PRD 0003)
- BYOK credential management (PRD 0006)
- Eventa event emission (PRD 0007)
- Per-request field overrides of ModelConfig values

---

## Background

Modela needs a stable foundation before adding routing, resilience, or advanced features. A single provider (OpenAI) implemented correctly gives us something shippable and establishes the core abstractions every future PRD builds on.

`ModelaModel` is that core abstraction. It wraps a pydantic-ai native model and intercepts every LLM call to apply gateway concerns — usage logging, ModelConfig parameters, credential resolution. Future PRDs extend `ModelaModel` rather than replacing it: PRD 0003 adds more providers to its factory, PRD 0008 adds MCP tool support on top of it.

The `model` field in the OpenAI-compatible request doubles as the ModelConfig slug. Modela performs a DB lookup on that value; if found, it uses the stored configuration. If not found, it raises an error — no silent fallback to raw model names.

---

## ModelConfig

### Purpose

A **ModelConfig** is a named, admin-managed configuration preset that encapsulates everything needed to execute a request against a provider. Consumers reference it by slug via the `model` field. They never need to know the underlying provider, model name, or system prompt.

### DB Schema

**Table: `model_configs`**

| Column          | Type         | Notes                                                                                                                               |
| --------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `id`            | UUID         | Primary key                                                                                                                         |
| `slug`          | VARCHAR(255) | Unique, URL-safe identifier used in API requests (e.g. `openai-gpt-4o`)                                                             |
| `name`          | VARCHAR(255) | Human-readable label                                                                                                                |
| `provider`      | VARCHAR(100) | Provider identifier (e.g. `openai`)                                                                                                 |
| `model`         | VARCHAR(255) | Provider-native model name (e.g. `gpt-4o`)                                                                                          |
| `system_prompt` | TEXT         | Optional. Prepended as a `system` message before user messages.                                                                     |
| `temperature`   | FLOAT        | Optional. Overrides provider default.                                                                                               |
| `max_tokens`    | INTEGER      | Optional.                                                                                                                           |
| `top_p`         | FLOAT        | Optional.                                                                                                                           |
| `output_schema` | JSONB        | Optional. JSON Schema definition for structured outputs (enforced in PRD 0002). Stored here but not validated until PRD 0002 ships. |
| `is_default`    | BOOLEAN      | Exactly one config may be marked default. Used when the `model` field is absent from the request.                                   |
| `created_at`    | TIMESTAMPTZ  | Auto-set                                                                                                                            |
| `updated_at`    | TIMESTAMPTZ  | Auto-updated                                                                                                                        |
| `deleted_at`    | TIMESTAMPTZ  | Soft delete                                                                                                                         |

**Constraints:**

- `slug` must be unique across non-deleted rows
- Only one row may have `is_default = true` at a time (enforced at application layer)
- `provider` must be a value in the registered provider registry (validated at write time)

### CRUD API

All endpoints require admin-level RBAC (`modela.model_config:*`).

| Method   | Path                  | Description                       |
| -------- | --------------------- | --------------------------------- |
| `POST`   | `/model-configs`      | Create a ModelConfig              |
| `GET`    | `/model-configs`      | List all ModelConfigs (paginated) |
| `GET`    | `/model-configs/{id}` | Get by id                         |
| `PUT`    | `/model-configs/{id}` | Update fields                     |
| `DELETE` | `/model-configs/{id}` | Soft delete                       |

**Request body (create/update):**

```json
{
  "slug": "openai-gpt-4o",
  "name": "OpenAI GPT-4o (Standard)",
  "provider": "openai",
  "model": "gpt-4o",
  "system_prompt": "You are a helpful assistant.",
  "temperature": 0.7,
  "max_tokens": 2048,
  "top_p": 1.0,
  "output_schema": null,
  "is_default": false
}
```

---

## ModelaModel

`ModelaModel` implements pydantic-ai's `Model` protocol. It wraps a pydantic-ai native model and intercepts each request to apply Modela's gateway concerns. In PRD 0001 the only inner model is `OpenAIModel`; PRD 0003 extends the factory for Anthropic and Ollama.

```python
class ModelaModel(pydantic_ai.models.Model):
    def __init__(
        self,
        model_config: ModelConfig,
        resolved_api_key: str,
        project_id: str,
        settings: Settings,
    ):
        self._model_config = model_config
        self._project_id = project_id
        self._inner = OpenAIModel(
            model_config.model,
            provider=OpenAIProvider(api_key=resolved_api_key),
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
    ) -> tuple[ModelResponse, Usage]:
        effective_settings = _apply_config_params(self._model_config, model_settings)

        start = time.monotonic()
        response, usage = await self._inner.request(messages, effective_settings)
        latency_ms = int((time.monotonic() - start) * 1000)

        log_completion_usage.delay(
            project_id=self._project_id,
            model_config_slug=self._model_config.slug,
            provider=self._model_config.provider,
            model=self._model_config.model,
            input_tokens=usage.request_tokens or 0,
            output_tokens=usage.response_tokens or 0,
            latency_ms=latency_ms,
        )

        return response, usage
```

`_apply_config_params` copies `temperature`, `max_tokens`, and `top_p` from the ModelConfig onto `model_settings`, with config values taking precedence over anything the caller supplied in `extra_body`.

`create_completion_command` constructs a `ModelaModel`, creates a pydantic-ai `Agent`, and calls `agent.run()`:

```python
model = ModelaModel(config, resolved_api_key, project_id, settings)
agent = Agent(model=model)
result = await agent.run(messages)
```

`Agent.run()` without toolsets is a single LLM call — no loop overhead. PRD 0008 passes `MCPToolset` instances to enable the agentic loop.

---

## Completion Endpoint

### `POST /chat/completions`

Accepts an OpenAI-compatible request body. Requires authentication and `modela.completion:create` RBAC permission.

**Query parameters:**

- `project_id` (optional) — used to populate the usage record and scope RBAC. Defaults to `"*"` if absent.

**Request:**

```json
{
  "model": "openai-gpt-4o",
  "messages": [{ "role": "user", "content": "Summarize this document." }],
  "extra_body": {}
}
```

**Resolution flow:**

1. If `model` field is present → treat as ModelConfig slug, look up by slug in DB
   - If not found → `404 ModelConfigNotFound`
2. If `model` field is absent → load the ModelConfig where `is_default = true`
   - If no default exists → `404 NoDefaultModelConfig`
3. If `system_prompt` is set on config → prepend as `{"role": "system", "content": "..."}` to messages
4. Apply inference parameters from config (temperature, max_tokens, top_p)
5. Merge `extra_body` into the provider request body (config values take precedence; `extra_body` is for non-overlapping provider-specific params)
6. Construct `ModelaModel`, create `Agent`, call `agent.run(messages)`
7. Write usage record (async, non-blocking)
8. Return provider response verbatim

**Response:** OpenAI-compatible chat completion object (passed through from provider).

**Errors:**

| Code  | Condition                                               |
| ----- | ------------------------------------------------------- |
| `404` | ModelConfig slug not found                              |
| `404` | `model` absent and no default ModelConfig is configured |
| `502` | Provider request failed                                 |
| `504` | Provider request timed out                              |

### Headers

- `X-Modela-Config-Slug` — echoed in response for debugging
- `X-Modela-Request-Id` — internal request UUID for tracing

---

## Credential Management (Phase 1)

Provider API keys are loaded from environment variables / application config. No DB storage in this phase.

```
OPENAI_API_KEY=sk-...
```

The OpenAI adapter reads `settings.openai_api_key` at startup. If absent, the adapter raises a configuration error on first use.

---

## Usage Logging

Every completed request writes a usage record asynchronously (fire-and-forget Celery task, does not block the response).

**Table: `completion_requests`**

| Column              | Type          | Notes                                                                          |
| ------------------- | ------------- | ------------------------------------------------------------------------------ |
| `id`                | UUID          | Primary key                                                                    |
| `request_id`        | VARCHAR       | `X-Modela-Request-Id` value                                                    |
| `project_id`        | VARCHAR       | From `project_id` query parameter on the request (defaults to `"*"` if absent) |
| `model_config_slug` | VARCHAR       | Slug used                                                                      |
| `provider`          | VARCHAR       | Resolved provider name                                                         |
| `model`             | VARCHAR       | Resolved model name                                                            |
| `input_tokens`      | INTEGER       |                                                                                |
| `output_tokens`     | INTEGER       |                                                                                |
| `latency_ms`        | INTEGER       | Wall-clock time from request to provider response                              |
| `cost_estimate_usd` | NUMERIC(12,8) | Calculated from known token pricing                                            |
| `finish_reason`     | VARCHAR       | `stop`, `length`, `content_filter`, etc.                                       |
| `created_at`        | TIMESTAMPTZ   |                                                                                |

Cost estimation is stubbed as `0` in Phase 1. Provider-based pricing will be added in a later phase.

---

## Dependencies

- Tessera Identies: auth context (already integrated)
- Tessera Custos: RBAC for ModelConfig admin endpoints (already integrated)
- `pydantic-ai[openai]` (new dependency — `ModelaModel` + `OpenAIModel`)
- `openai` Python SDK (pulled in transitively by pydantic-ai)
- Celery + Redis: async usage logging (already present)

---

## Success Criteria

- `POST /chat/completions` with a valid ModelConfig slug returns an OpenAI-compatible response
- Invalid slug returns `404` with a clear error message
- `system_prompt`, `temperature`, `max_tokens`, `top_p` from ModelConfig are applied to every request
- `extra_body` fields are forwarded to OpenAI without modification
- A `completion_requests` row is written for every successful request
- ModelConfig CRUD endpoints are accessible to admins and rejected for non-admins
- All new code has test coverage (unit + integration)

---

## Amendment — PRD 0008 Extension

PRD 0008 extends `ModelaModel` with MCP tool support. It adds `MCPToolset` instances to the `Agent` call and a `max_tool_rounds` field to ModelConfig. The `ModelaModel` class itself is unchanged — the gateway interceptor pattern established here carries through the entire PRD stack.

---

## Testing

**ModelaModel**
- Config params (`temperature`, `max_tokens`, `top_p`) are applied to model settings; unset fields are not forwarded
- `log_completion_usage` Celery task is dispatched after each call with correct token counts and latency
- `ModelaModel` with a mocked inner model returns the inner model's response unchanged

**Completion endpoint (`POST /chat/completions`)**
- Valid slug resolves config and returns an OpenAI-compatible response
- Unknown slug returns `404 ModelConfigNotFound`
- Absent `model` field with a default config set returns a response
- Absent `model` field with no default config returns `404 NoDefaultModelConfig`
- `system_prompt` on config is prepended as a system message before user messages
- Request without auth returns `401`
- Request without `modela.completion:create` permission returns `403`

**ModelConfig CRUD**
- Create stores all fields and returns the created record
- `is_default: true` on create clears the previous default row
- `is_default: true` on update clears the previous default row
- Duplicate slug returns `422`
- Unknown `provider` value returns `422`
- Delete soft-deletes the row (subsequent GET returns `404`, row still in DB)
- List endpoint returns paginated results and excludes soft-deleted rows

**`ModelConfigRepository`**
- `get_by_id` returns the record for a known id; returns `None` for an unknown id
- `get_by_id` returns `None` for a soft-deleted record without `skip_soft_delete_filter`
- `get_by_slug` returns the correct record; returns `None` when slug does not exist
- `get_default` returns the record with `is_default=True`; returns `None` when no default is set
- `list` excludes soft-deleted records and returns paginated results

**Commands**
- `create_model_config_command`: persists all fields; when `is_default=True`, clears `is_default` on all other rows before setting the new one
- `update_model_config_command`: updates only the supplied fields; when `is_default=True`, clears previous default
- `delete_model_config_command`: sets `deleted_at`; record is excluded from subsequent list and get queries

**Routers (`model_config_router`)**
- `POST /model-configs` with valid body returns `201` and the created record
- `GET /model-configs` returns a paginated envelope (`items`, `total`, `page`, `size`)
- `GET /model-configs/{id}` for a soft-deleted id returns `404`
- `PUT /model-configs/{id}` with a partial body updates only the supplied fields
- All model-config endpoints return `403` without `modela.model_config:*` permission

**`llm_calls` table**
- A row is written for every successful completion with correct `model_config_slug`, `provider`, `model`, `input_tokens`, `output_tokens`, `latency_ms`
