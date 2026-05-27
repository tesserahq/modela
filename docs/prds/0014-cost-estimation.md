## Problem Statement

Modela logs every LLM completion request in the `completion_requests` table, capturing input and output token counts per call. The `cost_estimate_usd` column exists but is always stored as `0` — meaning operators have no visibility into the actual dollar cost of inference. Without cost data, it is impossible to track spend by project, model, or time period, or to make informed decisions about model selection.

## Solution

Automatically calculate a USD cost estimate for each completion request by deriving it from the token counts already captured, using published provider pricing data. The calculation happens inside the existing Celery task that logs usage, keeping it fully off the hot request path. Provider pricing is kept up-to-date by running a background price-sync daemon inside each Celery worker process, fetching fresh rates from the `genai-prices` GitHub-hosted dataset immediately on worker start and then every hour.

## User Stories

1. As an operator, I want each logged completion request to include a non-zero cost estimate in USD, so that I can understand the actual cost of inference calls.
2. As an operator, I want cost estimates to reflect current provider pricing, so that my cost data doesn't silently become inaccurate when providers change their rates.
3. As an operator, I want cost estimates to be calculated for both OpenAI and Anthropic models, so that I have coverage across all supported providers.
4. As an operator, I want the system to gracefully handle models that have no known pricing data, so that a missing price never blocks a completion or drops a usage log.
5. As an operator, I want cost to be broken down into input and output token costs, so that I can understand the cost structure of different prompt/completion patterns.
6. As an operator, I want cost estimation to have no impact on response latency, so that users don't experience slower completions due to pricing lookups.
7. As an operator, I want pricing data to be refreshed automatically without requiring a redeploy, so that rate changes take effect within an hour.
8. As a developer, I want the cost calculation logic to be contained in a single, well-defined location, so that it is easy to test and reason about.
9. As a developer, I want the pricing library to be a transitive dependency already present in the project, so that no new packages need to be added to the lockfile.
10. As a developer, I want the worker startup to initialize the price-sync daemon once per process, so that there is no duplication or conflict between concurrent workers.

## Implementation Decisions

### Cost Calculation Module

A new internal pricing utility will be introduced to encapsulate the `genai_prices.calc_price()` call. It accepts a provider identifier, model name, input token count, and output token count, and returns a `Decimal` cost or `0` if the model is not found in the pricing database. This keeps the `LookupError` handling in one place and makes the logic unit-testable without touching the task or the worker.

### Where Cost is Calculated

Cost calculation moves entirely into the `log_completion_usage` Celery task. The task already receives `provider`, `model`, `input_tokens`, and `output_tokens` — all the data needed for a price lookup. The `model.py` inference layer continues to pass `cost_estimate_usd=0.0` when firing the task; the task is now responsible for computing the real value before writing to the database.

This keeps cost estimation fully off the hot request path and ensures it runs asynchronously.

### Pricing Library

`genai_prices` (from the `pydantic/genai-prices` project) is used for pricing lookups. It is already installed as a transitive dependency of `pydantic-ai` — no new package additions are required. The library ships with bundled static pricing data and optionally fetches updated data from a GitHub-hosted JSON file.

The provider identifiers used in Modela's adapter registry (`"openai"`, `"anthropic"`) match the `provider_id` values expected by `genai_prices.calc_price()` exactly, so no mapping layer is needed.

### Price Auto-Update

`genai_prices.UpdatePrices` is started inside each Celery worker process using Celery's `worker_init` signal. It fetches fresh prices immediately on start, then every hour thereafter using a daemon thread. It is stopped cleanly on `worker_shutdown`. This means pricing data is never more than one hour stale in a running system, without requiring a redeploy.

`UpdatePrices` enforces a singleton constraint (only one instance per process), so the signal-based approach is the correct integration point.

### Unknown Model Handling

If `calc_price` raises `LookupError` for a model not in the pricing database (e.g. fine-tuned models, private endpoints), the pricing utility returns `Decimal("0")` silently. The task stores `0.0` for `cost_estimate_usd`, identical to current behavior. No error is raised and the log record is still written.

### Schema

No schema changes are required. The `cost_estimate_usd` column (`Numeric(12, 8)`, default `0`) already exists on `completion_requests` and is wide enough to store the calculated value accurately.

## Testing Decisions

Good tests verify external behavior — what comes out given a known input — not implementation details like which internal function is called. Tests should not mock `genai_prices` internals; instead, they should pass known token counts and assert on the resulting stored `cost_estimate_usd` value (non-zero for known models, zero for unknown ones).

### Modules to Test

**Pricing utility** — Unit tests covering:
- Returns a positive `Decimal` for a known provider/model combination (e.g. `openai` / `gpt-4o`)
- Returns `Decimal("0")` for an unknown model without raising
- Returns `Decimal("0")` for an unknown provider without raising
- Input and output token counts are reflected proportionally in the result

**`log_completion_usage` task** — Integration tests (using the existing test DB session pattern) covering:
- A task invocation with a known model writes a non-zero `cost_estimate_usd` to the database
- A task invocation with an unknown model writes `0` to the database without error
- `input_tokens` and `output_tokens` are still stored correctly alongside the cost

### Prior Art

The existing test suite uses function-scoped DB sessions with transaction rollback. Task tests should follow the same pattern as other repository-layer tests, calling the task function directly (not via `.delay()`) with a real DB session.

## Out of Scope

- Exposing cost data via API endpoints or dashboards (querying `completion_requests` directly is sufficient for now)
- Per-project or per-model cost budgets or alerts
- Cost estimation for streaming completions (not currently supported)
- Retroactively backfilling `cost_estimate_usd` for historical records where it is `0`
- Supporting providers beyond OpenAI and Anthropic
- Caching or memoizing price lookups within a single worker lifecycle

## Further Notes

The `genai_prices` library fetches pricing data from `https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json`. This is a public URL with no authentication. If the fetch fails (network error, timeout), the library continues using the last successfully fetched snapshot or the bundled static data — it does not raise or crash the worker.

The `cost_estimate_usd` field is named an "estimate" intentionally. Provider invoices may differ due to rounding, promotional pricing, enterprise agreements, or features not captured in the public pricing table (e.g. batch discounts, cached token pricing tiers).
