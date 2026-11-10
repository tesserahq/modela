# PRD 0023: Provider model catalog change history

## Problem Statement

The weekly provider model catalog check (PRD 0018) detects when a provider adds or removes a model, and it publishes a NATS event. That event is the only record. Nothing in Modela stores it, and the web app doesn't show it. A team member has to know to look at the event stream to learn that `gpt-4.1-nano` or `o4-mini` is no longer served by OpenAI.

Two further gaps follow from the current implementation:

- A removed model is re-detected every week until someone edits the curated list in code. There is no memory of what was already reported.
- When a provider's live fetch fails (missing key, network error, non-2xx), the check logs the error and skips the provider. A broken check looks the same as a quiet week.

## Solution

Store each detected change, and each failed check, in Modela's database. Expose the history through the API. Show it in the web app on a dedicated "Model catalog changes" page, where a signed-in user can mark an entry as reviewed.

The weekly task keeps publishing its NATS events. It also writes the results to the database. It does not change any code or curated lists.

## Behaviour

**Change detection.** For each provider, the task compares the live model list with the previous snapshot. On the first run there is no previous snapshot, so it compares with the curated `_models` list in the adapter. Each detected difference becomes one history entry:

- `added`: a live model, within the provider's model-id prefixes, that the baseline doesn't contain.
- `removed`: a baseline model that the live list no longer contains.

A model that stays missing is recorded once, when it first disappears. On later runs the baseline is the snapshot from the previous run, so an unchanged difference produces no new entry.

**Snapshot.** After a successful fetch, the task stores the set of live model ids for that provider as the new snapshot. The snapshot is replaced only on success. A failed fetch leaves the previous snapshot unchanged, so a failure can't cause false changes on the next run.

**Failures.** When a provider's fetch fails, the task records a `check_failed` entry for that provider, with the error category (for example `missing_key`, `network`, or `http_error`) and the time. It doesn't record the error message, to avoid storing sensitive details. The snapshot is left unchanged.

**Reviewing.** Any signed-in user can mark an entry as reviewed. The entry records who marked it and when. Reviewing is recorded, but it doesn't change the entry's type or the snapshot.

**Retention.** History is kept indefinitely. Volume is low: at most a few rows per provider per week.

**Events.** The NATS publish (`provider_model.added` / `provider_model.removed`) is unchanged and still follows the drift diff. The database write and the publish happen in the same task run.

## Data model

Two tables, both additive (expand/contract rule in `AGENTS.md`):

- `provider_model_catalog_entries`: id, provider_id, kind (`added`, `removed`, `check_failed`), model_id (nullable for `check_failed`), error_category (nullable), detected_at, reviewed_at (nullable), reviewed_by_id (nullable, user FK), created_at, updated_at. Soft-delete mixin is not needed; entries are never deleted.
- `provider_model_catalog_snapshots`: provider_id (primary key), model_ids (JSON list), captured_at. One row per provider, replaced on each successful fetch.

Each table gets a model in `app/models/`, is exported from `app/models/__init__.py`, and gets an alembic migration.

## API

- `GET /providers/catalog-changes`: paginated list (fastapi-pagination with `select(...)`), filters `provider_id`, `kind`, `reviewed` (true/false). Ordered by `detected_at` descending. Requires an authenticated user (same as `GET /providers`).
- `PATCH /providers/catalog-changes/{entry_id}`: sets `reviewed` to true and records the current user. Setting it to false clears both fields. Requires the `update` permission (checked with `rbac["update"]`), not only `read`, because it changes stored data. Returns 404 through `ResourceNotFoundError`.

Both routes use the existing auth dependency. The list uses `read`; the PATCH uses `update`. Neither is restricted to admins.

## Web app

A "Model catalog changes" page in the main navigation. The list shows the detected time, provider, kind, model id or error category, and reviewed state (with reviewer and time). Filters: provider, kind, reviewed. Each row has a "Mark as reviewed" action. `check_failed` rows are visually distinct, so a broken check is easy to spot.

## Implementation notes

- The task writes to the database with its own session. Worker pool size is 1, so the task must not hold a connection while it fetches from providers. Fetch first, then open the session for the writes.
- Snapshot and entries are written in one transaction per provider, so a crash can't leave a snapshot without its entries.
- Model ids are compared exactly as the provider returns them. The existing prefix filters from PRD 0018 still apply.

## Testing

- Diff logic: the first run compares with curated ids; later runs compare with the snapshot; an unchanged difference produces no entry; a failed fetch leaves the snapshot untouched and records `check_failed`. Test the failure case first, since a wrong snapshot update would produce false history.
- Task: entries and snapshot are written together; a provider failure doesn't affect other providers.
- API: list filters and pagination; PATCH sets and clears the reviewer; unknown id returns 404.
- Web app: list, filter, and mark-as-reviewed flows.

## Out of Scope

- Automatically updating curated lists or opening PRs.
- Notifications beyond the existing NATS event (no email or Slack).
- Admin-only visibility.
- Pricing or cost-tier changes detected by the check.
- Retention or pruning policy beyond keeping everything.

## Open Questions

- The error category vocabulary (`missing_key`, `network`, `http_error`, and others) should be fixed in the code before implementation, so the web app can rely on it.
- Whether the NATS event for a `check_failed` provider should also be published. The current design publishes nothing for a failed fetch. This PRD keeps that behaviour.
