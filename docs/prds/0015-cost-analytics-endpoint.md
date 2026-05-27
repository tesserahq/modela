## Problem Statement

Modela logs every LLM completion request with a `cost_estimate_usd` value, but there is no way to query aggregated cost data. The only existing endpoint lists raw records with basic project filtering. Operators have no way to answer questions like "who is spending the most?", "which model is the most expensive?", or "how much did we spend on Anthropic this month?" — without pulling all records and aggregating them externally.

## Solution

A new `GET /analytics/costs` endpoint that returns total spend grouped by a single chosen dimension (`user`, `provider`, `model`, or `project_id`), with optional filters on any of those dimensions plus a date range. Results are sorted by `total_cost_usd` descending so the highest spenders appear first.

## User Stories

1. As an operator, I want to see total spend grouped by user, so that I can identify who is driving the most cost.
2. As an operator, I want to see total spend grouped by provider, so that I can compare spend across OpenAI, Anthropic, and other providers.
3. As an operator, I want to see total spend grouped by model, so that I can understand which models are the most expensive.
4. As an operator, I want to see total spend grouped by project, so that I can allocate costs to teams or products.
5. As an operator, I want to filter cost results by a start and end date, so that I can analyze spend for a specific billing period.
6. As an operator, I want to filter cost results by project, so that I can drill into a single project's spend breakdown.
7. As an operator, I want to filter cost results by provider while grouping by model, so that I can see the cost breakdown of a single provider's models.
8. As an operator, I want to filter cost results by model while grouping by user, so that I can see which users are driving cost for a specific model.
9. As an operator, I want unattributed requests (no `created_by_id`) to appear as a `null` bucket when grouping by user, so that I can see the full spend picture including requests that weren't tied to a specific user.
10. As an operator, I want cost results sorted from highest to lowest spend by default, so that I can immediately see who or what is spending the most without additional sorting.
11. As an operator, I want the cost endpoint to return a plain list (not paginated), so that I can consume the full ranked list in a single request.
12. As a developer, I want the analytics endpoint to use the same RBAC resource as the existing completion request endpoints, so that access control is consistent and no new permissions need to be configured.
13. As a developer, I want the aggregation query to live in the existing `CompletionRequestRepository`, so that all database access for this model is in one place.
14. As a developer, I want a dedicated Pydantic response schema for cost summary rows, so that the API contract is explicit and independently evolvable.

## Implementation Decisions

### New Router: Analytics

A new `analytics_router` is introduced with the prefix `/analytics` and tag `analytics`. It is registered in the app factory alongside the existing routers. This keeps the door open for future analytics endpoints without coupling them to the completion-request resource.

### Endpoint Contract

```
GET /analytics/costs
```

Query parameters:
- `group_by` (required): one of `user`, `provider`, `model`, `project_id`
- `start_date` (optional): ISO date — filters `created_at >= start_date`
- `end_date` (optional): ISO date — filters `created_at < end_date + 1 day` (inclusive end)
- `project_id` (optional): exact match filter
- `provider` (optional): exact match filter
- `model` (optional): exact match filter
- `created_by_id` (optional): UUID filter, exact match

Response: a plain JSON array of cost summary objects, sorted by `total_cost_usd` descending.

Each row contains:
- The group key field (e.g. `provider: "openai"`, `model: "gpt-4o"`, `project_id: "proj-a"`, `created_by_id: "<uuid>"`)
- `total_cost_usd`: summed cost as a decimal string

The group key value may be `null` for the unattributed bucket (e.g. when grouping by user and `created_by_id IS NULL`).

### Response Schema

A new `CostSummaryItem` Pydantic schema is added to the completion request schemas module. It contains:
- `group_key`: the dimension name (matches the `group_by` parameter value)
- `group_value`: the value for that dimension (string, UUID, or `null`)
- `total_cost_usd`: `Decimal`

### Repository Method

A new `cost_summary_query` method is added to `CompletionRequestRepository`. It accepts:
- `group_by`: a string enum value mapping to a column
- All optional filter parameters (same set as the endpoint)

It returns a SQLAlchemy `Select` that uses `func.sum(CompletionRequest.cost_estimate_usd)` grouped by the chosen column, with all active filters applied, ordered by the sum descending.

The router calls this method, executes the query, and maps results to `CostSummaryItem` objects before returning.

### RBAC

The analytics router uses the same `completion_request` RBAC resource with `read` action, consistent with the existing list endpoint. No new permissions are needed.

### Date Filtering

`start_date` and `end_date` are `datetime.date` values. The filter applies `created_at >= start_date` (start of day, UTC) and `created_at < end_date + timedelta(days=1)` (exclusive upper bound, making `end_date` inclusive).

### No Pagination

The response is a plain `list[CostSummaryItem]`. Grouped results have at most as many rows as there are distinct values in the grouping column, which is small enough that pagination adds no value.

## Testing Decisions

Good tests assert on what comes out of the API given a known DB state — not on which internal SQL functions were called. Tests seed `CompletionRequest` records with known `cost_estimate_usd` values and assert that the grouped totals match expectations.

### Modules to Test

**Analytics router** — Integration tests following the same pattern as `test_completion_request_router.py`:

- `group_by=provider` returns one row per distinct provider, totals match sum of seeded costs
- `group_by=model` returns one row per distinct model
- `group_by=user` returns one row per distinct `created_by_id`, including a `null` row for unattributed requests
- `group_by=project_id` returns one row per distinct project
- Results are sorted by `total_cost_usd` descending
- `start_date` / `end_date` filters exclude records outside the window
- `project_id` filter limits results to that project
- `provider` filter limits results before grouping
- `model` filter limits results before grouping
- `created_by_id` filter limits to that user's spend
- Combining filters works correctly (e.g. `provider=openai&group_by=model`)
- Missing `group_by` parameter returns a 422 validation error
- Invalid `group_by` value returns a 422 validation error

### Prior Art

`tests/routers/test_completion_request_router.py` — seeding via `CompletionRequestRepository.create()` with `CompletionRequestCreate` payloads, using the function-scoped `db` fixture and `client` fixture.

## Out of Scope

- Grouping by multiple dimensions simultaneously (e.g. user + provider)
- Aggregations beyond total cost (request count, average cost, token totals)
- Joining to the users table to resolve `created_by_id` to a name or email
- Time-bucketed aggregations (daily, weekly, monthly rollups)
- Sorting by any dimension other than `total_cost_usd`
- Pagination of cost summary results
- Cost budgets, alerts, or quota enforcement
- Retroactive cost recalculation

## Further Notes

The `group_by` parameter maps directly to ORM columns on `CompletionRequest`. Validate it as a string enum at the schema/router level to prevent injection through dynamic column selection.

Date filter semantics: `end_date` is treated as inclusive (the full day is included). This matches typical billing period UX where "May 1 to May 31" means all of May.
