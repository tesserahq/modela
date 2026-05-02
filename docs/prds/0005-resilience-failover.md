# PRD 0005 — Resilience & Failover

## Overview

This phase makes Modela fault-tolerant. It introduces retry policies, fallback provider chains, configurable timeouts, and a circuit breaker. These features are configured on **ModelConfig**, keeping the consumer API unchanged — callers get a reliable response without knowing a failover happened.

---

## Goals

- Retry failed provider requests with exponential backoff
- Support fallback chains: if a provider fails after retries, try the next ModelConfig in the chain
- Add configurable per-ModelConfig request timeouts
- Implement a circuit breaker to stop sending requests to a provider that is consistently failing
- Log all retry and failover events for observability
- Keep the consumer API completely unchanged

---

## Non-Goals

- Weighted load balancing / traffic splitting across providers (separate concern)
- Automatic provider selection based on latency or cost
- Streaming failover (if a stream starts and the provider fails mid-stream, the error is surfaced to the client; failover of in-progress streams is out of scope)

---

## Background

Multi-provider support (PRD 0003) gives Modela the ability to route to different backends. Resilience makes that routing reliable under failure conditions. The fallback chain is modelled as a linked list of ModelConfig slugs: if the primary fails, Modela resolves the next config in the chain and retries from scratch with that provider.

---

## ModelConfig Changes

Three new fields on `model_configs`:

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `timeout_ms` | INTEGER | `30000` | Per-request timeout in milliseconds |
| `retry_attempts` | INTEGER | `2` | Number of retry attempts before failing or falling back |
| `fallback_config_slug` | VARCHAR | `null` | Slug of the ModelConfig to use if this one fails after retries |

**Circular chain detection:** at write time, if setting `fallback_config_slug` would create a cycle (A → B → A), Modela returns a `422` validation error.

**Chain depth limit:** maximum fallback chain depth is 5. Chains longer than this are rejected at write time.

---

## Retry Policy

Retries apply to transient errors: provider timeouts, `429` rate limit responses, `5xx` errors from the provider. They do not apply to `4xx` client errors (prompt rejected, content filter, invalid request).

**Backoff:** exponential with jitter.
- Attempt 1: immediate
- Attempt 2: 500ms ± jitter
- Attempt 3: 1000ms ± jitter

`retry_attempts` on ModelConfig controls how many retry attempts are made (not including the initial attempt). Default is `2`, so total attempts = 3.

---

## Fallback Chain

If all retries on the primary ModelConfig are exhausted:

1. Check `fallback_config_slug` on the current ModelConfig
2. If set: load that ModelConfig, reset retry counter, attempt request with new provider
3. Continue down the chain until a request succeeds or the chain is exhausted
4. If the entire chain fails: return the last error to the caller

The fallback is transparent to the caller. The response includes a header:

```
X-Modela-Fallback-Used: anthropic-claude-haiku
```

This indicates which ModelConfig ultimately served the request. If no fallback was used, the header is absent.

Usage logging records the **actual** config slug and provider used (not the originally requested one), plus a `fallback_from` field referencing the original slug.

### Usage record additions

| Column | Type | Notes |
|--------|------|-------|
| `fallback_from_slug` | VARCHAR | Original ModelConfig slug if a fallback was triggered |
| `attempt_count` | INTEGER | Total provider attempts (including retries and fallbacks) |

---

## Timeout Handling

The `timeout_ms` field on ModelConfig sets a hard deadline for the provider request (not including Modela's own processing time). If the provider does not respond within `timeout_ms`, the attempt is treated as a transient failure and triggers a retry or fallback.

Default: `30000` ms (30 seconds).

At the adapter level, this is passed as the `timeout` parameter to the SDK call.

---

## Circuit Breaker

A per-provider in-memory circuit breaker prevents hammering a failing provider.

**States:** `CLOSED` (normal) → `OPEN` (blocking) → `HALF_OPEN` (probing)

**Thresholds (configurable via app settings):**
```
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5     # failures in window to open
CIRCUIT_BREAKER_WINDOW_SECONDS=60       # rolling window
CIRCUIT_BREAKER_RECOVERY_SECONDS=30     # time before HALF_OPEN probe
```

When a circuit is `OPEN` for a provider, requests to that provider are short-circuited immediately (no network call) and treated as failures, triggering fallback if configured.

Circuit state is stored in Redis (shared across workers). State changes are logged.

The circuit breaker operates at the **provider** level (e.g. `openai`), not the ModelConfig level. All ModelConfigs using the same provider share one circuit.

---

## Error Surface

When all retries and fallbacks are exhausted, the response is:

```json
{
  "error": "ProviderChainExhausted",
  "message": "All configured providers failed.",
  "attempts": [
    { "config": "openai-gpt-4o", "attempts": 3, "last_error": "ProviderTimeout" },
    { "config": "anthropic-claude-haiku", "attempts": 3, "last_error": "ProviderRateLimit" }
  ]
}
```

HTTP status: `502`.

---

## Observability

Every retry, fallback, and circuit breaker state change is:
- Logged as a structured log event with `request_id`, `model_config_slug`, `provider`, `attempt`, `error`
- Recorded in the usage log (`attempt_count`, `fallback_from_slug`)

No new metrics endpoints are added in this phase; the existing OpenTelemetry instrumentation captures latency and error rates.

---

## Dependencies

- PRD 0001 (ModelConfig, usage logging, BaseProviderAdapter)
- PRD 0003 (multiple providers exist for fallback to be meaningful)
- Redis (already present, used for circuit breaker state)
- `tenacity` Python library for retry logic (new dependency)

---

## Success Criteria

- A request to a provider that returns `503` is retried up to `retry_attempts` times with backoff
- After retries are exhausted, the fallback ModelConfig is tried automatically
- The `X-Modela-Fallback-Used` header is present when a fallback was triggered
- A provider with `OPEN` circuit state is skipped immediately, triggering fallback
- Circular fallback chains are rejected at ModelConfig write time with `422`
- Usage records correctly reflect `attempt_count` and `fallback_from_slug`
- Non-retryable errors (content filter, bad request) are not retried
- All resilience paths have test coverage (provider failure simulation via mocks)
