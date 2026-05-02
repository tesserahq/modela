# PRD 0001 — Foundation & ModelConfig

## Overview

This phase delivers a working end-to-end AI gateway: a single OpenAI-compatible HTTP endpoint that resolves a named **ModelConfig**, forwards the request to OpenAI, and logs usage. It establishes the core abstractions all future phases build on.

---

## Goals

- Define the provider adapter interface all future providers implement
- Ship a working OpenAI adapter (non-streaming completions)
- Expose an OpenAI-compatible `POST /v1/chat/completions` endpoint
- Introduce **ModelConfig** as the central configuration primitive
- Log per-request usage (tokens, latency, cost estimate) to Postgres
- Keep platform credentials simple: env-var / config-based API keys

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

Modela needs a stable foundation before adding routing, resilience, or advanced features. A single provider (OpenAI) implemented correctly, behind a clean adapter interface, gives us something shippable and a pattern every future provider follows.

The `model` field in the OpenAI-compatible request doubles as the ModelConfig slug. Modela performs a DB lookup on that value; if found, it uses the stored configuration. If not found, it raises an error — no silent fallback to raw model names.

---

## ModelConfig

### Purpose

A **ModelConfig** is a named, admin-managed configuration preset that encapsulates everything needed to execute a request against a provider. Consumers reference it by slug via the `model` field. They never need to know the underlying provider, model name, or system prompt.

### DB Schema

**Table: `model_configs`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `slug` | VARCHAR(255) | Unique, URL-safe identifier used in API requests (e.g. `openai-gpt-4o`) |
| `name` | VARCHAR(255) | Human-readable label |
| `provider` | VARCHAR(100) | Provider identifier (e.g. `openai`) |
| `model` | VARCHAR(255) | Provider-native model name (e.g. `gpt-4o`) |
| `system_prompt` | TEXT | Optional. Prepended as a `system` message before user messages. |
| `temperature` | FLOAT | Optional. Overrides provider default. |
| `max_tokens` | INTEGER | Optional. |
| `top_p` | FLOAT | Optional. |
| `output_schema` | JSONB | Optional. JSON Schema definition for structured outputs (enforced in PRD 0002). Stored here but not validated until PRD 0002 ships. |
| `is_default` | BOOLEAN | Exactly one config may be marked default. Used when the `model` field is absent from the request. |
| `created_at` | TIMESTAMPTZ | Auto-set |
| `updated_at` | TIMESTAMPTZ | Auto-updated |
| `deleted_at` | TIMESTAMPTZ | Soft delete |

**Constraints:**
- `slug` must be unique across non-deleted rows
- Only one row may have `is_default = true` at a time (enforced at application layer)
- `provider` must be a value in the registered provider registry (validated at write time)

### CRUD API

All endpoints require admin-level RBAC (`modela.model_config:*`).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/model-configs` | Create a ModelConfig |
| `GET` | `/v1/model-configs` | List all ModelConfigs (paginated) |
| `GET` | `/v1/model-configs/{slug}` | Get by slug |
| `PATCH` | `/v1/model-configs/{slug}` | Update fields |
| `DELETE` | `/v1/model-configs/{slug}` | Soft delete |

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

## Provider Adapter Interface

Define a base class all provider adapters must implement:

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
```

**`CompletionResponse`** is an internal dataclass (not exposed directly) that maps to the OpenAI response shape:

```python
@dataclass
class CompletionResponse:
    id: str
    model: str
    content: str
    role: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    raw: dict  # full provider response, passed through to caller
```

The `raw` field is returned verbatim to the consumer so no provider capability is lost.

---

## Completion Endpoint

### `POST /v1/chat/completions`

Accepts an OpenAI-compatible request body.

**Request:**
```json
{
  "model": "openai-gpt-4o",
  "messages": [
    { "role": "user", "content": "Summarize this document." }
  ],
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
5. Merge `extra_body` into the provider request body
6. Forward to OpenAI adapter
7. Write usage record (async, non-blocking)
8. Return provider response verbatim

**Response:** OpenAI-compatible chat completion object (passed through from provider).

**Errors:**

| Code | Condition |
|------|-----------|
| `404` | ModelConfig slug not found |
| `404` | `model` absent and no default ModelConfig is configured |
| `502` | Provider request failed |
| `504` | Provider request timed out |

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

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `request_id` | VARCHAR | `X-Modela-Request-Id` value |
| `project_id` | UUID | From authenticated request context (Tessera project) |
| `model_config_slug` | VARCHAR | Slug used |
| `provider` | VARCHAR | Resolved provider name |
| `model` | VARCHAR | Resolved model name |
| `input_tokens` | INTEGER | |
| `output_tokens` | INTEGER | |
| `latency_ms` | INTEGER | Wall-clock time from request to provider response |
| `cost_estimate_usd` | NUMERIC(12,8) | Calculated from known token pricing |
| `finish_reason` | VARCHAR | `stop`, `length`, `content_filter`, etc. |
| `created_at` | TIMESTAMPTZ | |

Cost estimation uses a static pricing table in code (per provider/model, updated manually). No external pricing API in this phase.

---

## OpenAI Adapter

- Uses the `openai` Python SDK
- Calls `client.chat.completions.create(...)` with resolved parameters
- Merges `extra_body` using the SDK's `extra_body` parameter
- Maps SDK response to `CompletionResponse`
- Raises `ProviderError` on API errors, `ProviderTimeoutError` on timeout

---

## Dependencies

- Tessera Identies: auth context (already integrated)
- Tessera Custos: RBAC for ModelConfig admin endpoints (already integrated)
- `openai` Python SDK (new dependency)
- Celery + Redis: async usage logging (already present)

---

## Success Criteria

- `POST /v1/chat/completions` with a valid ModelConfig slug returns an OpenAI-compatible response
- Invalid slug returns `404` with a clear error message
- `system_prompt`, `temperature`, `max_tokens`, `top_p` from ModelConfig are applied to every request
- `extra_body` fields are forwarded to OpenAI without modification
- A `completion_requests` row is written for every successful request
- ModelConfig CRUD endpoints are accessible to admins and rejected for non-admins
- All new code has test coverage (unit + integration)
