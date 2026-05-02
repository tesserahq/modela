# PRD 0007 — Usage Attribution & Limits

## Overview

This phase operationalises usage data: emitting usage events to **Eventa**, enforcing per-project rate limits and token quotas, and exposing usage query endpoints. The `completion_requests` table introduced in PRD 0001 becomes the source of truth for attribution and limit enforcement.

---

## Goals

- Emit a structured usage event to Eventa after every completed request
- Enforce per-project rate limits (requests per minute) and token quotas (tokens per day/month)
- Expose usage query endpoints for consumers (own project) and admins (any project)
- Return a clear, actionable error when a limit is exceeded
- Keep limit enforcement synchronous and non-blocking for the happy path

---

## Non-Goals

- Real-time billing or invoicing
- Cost alerts or budget notifications (future)
- Per-ModelConfig limits (limits are per project in this phase)
- Automatic quota top-ups or purchasing

---

## Background

PRD 0001 logs raw usage to Postgres. That data is usable for internal reporting but is not yet wired into the Tessera observability ecosystem (Eventa) or used to enforce any limits. This phase closes both gaps.

Usage must be attributable at the `project_id` level so that downstream services (e.g. Linden, which maps `project_id` to `account_id`) can understand their AI resource consumption.

---

## Eventa Integration

After every successful completion (streaming or non-streaming), a usage event is emitted to Eventa via the existing NATS-based event pipeline.

**Event type:** `modela.completion.completed`

**Payload:**
```json
{
  "event_type": "modela.completion.completed",
  "project_id": "uuid",
  "request_id": "uuid",
  "model_config_slug": "openai-gpt-4o",
  "provider": "openai",
  "model": "gpt-4o",
  "input_tokens": 512,
  "output_tokens": 128,
  "cost_estimate_usd": "0.00384000",
  "latency_ms": 1240,
  "finish_reason": "stop",
  "fallback_from_slug": null,
  "attempt_count": 1,
  "streamed": false,
  "occurred_at": "2026-05-01T14:23:00Z"
}
```

Emission is asynchronous (Celery task, fire-and-forget after the response is returned). If emission fails, it is retried via Celery retry policy. A failed emission does not affect the caller response.

---

## Quota & Rate Limit Model

**Table: `project_quotas`**

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `id` | UUID | | Primary key |
| `project_id` | UUID | | Unique |
| `rpm_limit` | INTEGER | `null` | Max requests per minute. `null` = unlimited |
| `daily_token_limit` | INTEGER | `null` | Max tokens per calendar day (UTC). `null` = unlimited |
| `monthly_token_limit` | INTEGER | `null` | Max tokens per calendar month (UTC). `null` = unlimited |
| `created_at` | TIMESTAMPTZ | | |
| `updated_at` | TIMESTAMPTZ | | |

Quotas are admin-managed only. If no row exists for a project, limits are unlimited.

---

## Limit Enforcement

Enforcement runs **before** the provider call, so quota-exceeded requests are rejected without incurring provider cost.

### Rate limit (RPM)

Implemented with a Redis sliding window counter:

```
key: modela:rpm:{project_id}
TTL: 60 seconds
```

On each request:
1. `INCR modela:rpm:{project_id}`
2. If the key is new, set TTL to 60s
3. If count > `rpm_limit` → reject with `429`

The counter is incremented atomically using a Lua script to avoid race conditions.

### Token quota (daily / monthly)

Token quotas are checked against the `completion_requests` table (aggregated at check time):

```sql
SELECT COALESCE(SUM(input_tokens + output_tokens), 0)
FROM completion_requests
WHERE project_id = :project_id
  AND created_at >= :window_start
  AND deleted_at IS NULL
```

`window_start` is the start of the current UTC day (daily) or month (monthly).

This query is run before the provider call. Because it reads from the DB, it is slightly slower than the Redis RPM check but is consistent across all workers without additional synchronisation.

**Optimisation:** results are cached in Redis with a short TTL (5 seconds) to reduce DB load on high-volume projects.

### Limit exceeded response

```json
{
  "error": "QuotaExceeded",
  "message": "Daily token limit exceeded for this project.",
  "limit_type": "daily_token",
  "limit": 1000000,
  "used": 1001482,
  "reset_at": "2026-05-02T00:00:00Z"
}
```

HTTP status: `429` for rate limits, `402` for quota exhaustion.

`reset_at` tells the caller when the limit resets.

---

## Usage Query API

### Consumer endpoints

Consumers can query their own usage. `project_id` is from auth context.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/usage` | Usage summary for caller's project |
| `GET` | `/v1/usage/requests` | Paginated list of individual completion requests |

**`GET /v1/usage` response:**
```json
{
  "project_id": "uuid",
  "period": {
    "today": {
      "input_tokens": 12400,
      "output_tokens": 3200,
      "requests": 48,
      "cost_estimate_usd": "0.49280000"
    },
    "this_month": {
      "input_tokens": 284000,
      "output_tokens": 71000,
      "requests": 1104,
      "cost_estimate_usd": "11.24800000"
    }
  },
  "quotas": {
    "rpm_limit": 60,
    "daily_token_limit": 500000,
    "monthly_token_limit": null
  }
}
```

### Admin endpoints

RBAC: `modela.usage:read`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/admin/projects/{project_id}/usage` | Usage summary for any project |
| `GET` | `/v1/admin/projects/{project_id}/usage/requests` | Paginated request log |
| `POST` | `/v1/admin/projects/{project_id}/quotas` | Set or update quota for a project |
| `DELETE` | `/v1/admin/projects/{project_id}/quotas` | Remove quota (revert to unlimited) |

---

## Cost Estimation

Cost is calculated using a static pricing table in code:

```python
PRICING = {
    "openai": {
        "gpt-4o":            { "input": 0.0000025, "output": 0.00001 },
        "gpt-4o-mini":       { "input": 0.00000015, "output": 0.0000006 },
    },
    "anthropic": {
        "claude-opus-4-7":   { "input": 0.000015, "output": 0.000075 },
        "claude-sonnet-4-6": { "input": 0.000003, "output": 0.000015 },
        "claude-haiku-4-5":  { "input": 0.0000008, "output": 0.000004 },
    },
}
```

Prices are per token (USD). The table is updated manually when provider pricing changes. If a model is not in the table, `cost_estimate_usd` is recorded as `null`.

---

## Dependencies

- PRD 0001 (`completion_requests` table, Celery, Redis)
- PRD 0003 (multi-provider, for per-provider cost table to be meaningful)
- PRD 0005 (fallback metadata fields in usage records)
- NATS / Eventa infrastructure (already present via `app/messaging/`)

---

## Success Criteria

- A `modela.completion.completed` event is emitted to Eventa after every successful request
- Requests over `rpm_limit` are rejected with `429` before hitting the provider
- Requests over `daily_token_limit` or `monthly_token_limit` are rejected with `402`
- `reset_at` is accurate in the limit-exceeded response
- `GET /v1/usage` returns correct token and request counts for the caller's project
- Admin quota CRUD endpoints work and are inaccessible to non-admins
- Eventa emission failure does not affect the response to the caller
- All enforcement logic has unit tests with mocked Redis and DB
