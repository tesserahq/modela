## Problem Statement

Each provider adapter (`AnthropicProviderAdapter`, `OpenAIProviderAdapter`) hardcodes a curated `_models` list that `GET /providers` serves to consumers picking a model for a `ModelConfig`. Nothing keeps that list in sync with what the provider actually offers: when Anthropic or OpenAI ships a new model, nobody at modela is prompted to add it, so it stays unavailable until someone happens to notice. Conversely, when a provider retires a model, our list can keep offering an id that would fail at runtime if a customer picked it. There is currently no process, automated or manual, that checks provider drift.

## Solution

Add a weekly Celery Beat task that, for each registered provider adapter, fetches the provider's live model list and diffs it against that adapter's hardcoded `_models` list. When it finds a model the provider serves that we don't curate yet, or a model we curate that the provider no longer lists, it publishes a NATS event describing the diff. This is a notify-only mechanism: no code is changed automatically. A human reviews the event and adds a proper entry (name, description, cost tier) to the adapter's list through a normal PR, the same way the model catalog is maintained today.

This PRD builds on two pieces of prior cleanup in this codebase:
- The Anthropic adapter's `_models` list was already refreshed to mirror Anthropic's current `/v1/models` response, and `ProviderModelSchema` gained an optional `description` field.
- A dead NATS-consumer code path (`process_nats_event.py`, `run_nats_worker.py`, `start_nats_worker.sh`, `NatsEventSubscriber`) was removed — it was copied from another service and was never actually deployed for modela (confirmed against production's `docker-compose.yml`, which has no `modela-nats-worker` service, unlike sibling services that do run one). Modela is publish-only for NATS going forward, which is exactly the capability this feature needs.

Production already runs a `modela-beat` Celery Beat process; it just has no `beat_schedule` configured yet, so this feature requires no new deploy/infra work — only adding the schedule entry in code.

## User Stories

1. As a developer maintaining modela's provider catalog, I want to be notified when Anthropic or OpenAI ships a model we don't curate yet, so that I can add it without having to remember to check manually.
2. As a developer maintaining modela's provider catalog, I want to be notified when a model we curate is no longer served by the provider, so that I can remove or replace it before a customer's request fails against a deprecated id.
3. As an on-call engineer, I want a one-off failure to reach a provider's API (missing key, rate limit, network blip) to not crash the whole weekly check, so that one provider's outage doesn't hide drift on the other provider.
4. As a developer reviewing a detected change, I want the event to tell me which provider, which model id(s), and whether it's an addition or removal, so that I don't have to re-fetch the provider's model list myself to understand what changed.
5. As a developer, I want the "new model" signal to be based on real data (the provider's own `created_at` timestamp) rather than guessed from the id string, so that I can trust the detection isn't a false positive from an id-naming quirk.
6. As a developer, I want the check to ignore models modela doesn't serve at all (embeddings, audio, moderation, etc. from OpenAI's `/v1/models`), so that the weekly event isn't flooded with irrelevant noise.
7. As a developer adding a future third provider adapter, I want the drift-check mechanism to work automatically once I implement the adapter interface, so that I don't have to build a bespoke check for every new provider.
8. As a developer, I do not want this feature to auto-modify `_models` in code, so that every catalog change still goes through a normal, reviewable PR with a human-written description and cost tier.
9. As an operator, I want this task to run on the existing `modela-beat` process, so that no new deployment or process needs to be provisioned.

## Implementation Decisions

- **Scope**: covers both registered adapters (Anthropic, OpenAI), implemented generically against `BaseProviderAdapter` so any future adapter is covered automatically without bespoke code.
- **Live fetch**: `BaseProviderAdapter` gains a new abstract method (e.g. `fetch_live_model_ids()`) that each adapter implements by calling the provider's models-list endpoint (Anthropic: `GET /v1/models` with `X-Api-Key` + `anthropic-version` headers; OpenAI: `GET /v1/models` with a Bearer token), using the existing `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` settings. The method returns each live model's id and creation timestamp. This is a new outbound HTTP capability for modela — no existing HTTP client pattern in the codebase to extend.
- **Noise filtering**: each adapter defines a small hardcoded tuple of "family stem" prefixes, chosen once by a human from the ids already present in that adapter's `_models` list (e.g. Anthropic: `("claude",)`; OpenAI: `("gpt", "o")`). A live-fetched id is only considered in-scope for diffing if it starts with one of the adapter's stems. This excludes OpenAI's non-chat models (embeddings, whisper, tts, moderation, dall-e, etc.) which don't share those prefixes, without introducing a general model-category concept.
- **Diff basis**: no persisted "last known state." Each run fetches the provider's current live model list and diffs it directly against the adapter's current hardcoded `_models` list. Two outcomes are possible per adapter: ids the provider serves that aren't curated (additions), and curated ids the provider no longer serves (removals). The emitted event is the only historical record; nothing else stores diff history.
- **"Newer version" signal**: per family stem, compare the maximum `created_at` among currently-curated ids against the maximum `created_at` among live in-scope ids for that stem. A later live-side timestamp is treated as a signal worth surfacing in the addition event, distinguishing "a materially newer model in this line" from "just some other id we hadn't gotten around to adding." This uses data the provider already returns; nothing is inferred from the id text.
- **Scheduling**: add `celery_app.conf.beat_schedule` to `app/infra/celery_app.py` with a weekly entry pointing at the new task, following the pattern already used elsewhere (a dict entry with a `task` path and a `schedule`, either a crontab or an interval in seconds). No new process needs provisioning — production's existing `modela-beat` service will pick up the schedule automatically once deployed.
- **Task shape**: the new Celery task lives under `app/tasks/`, following the existing shape of tasks like `log_completion_usage` — a plain `@celery_app.task` function with its own logging, no shared mutable state. It iterates the provider registry, and for each adapter independently: fetches live models, filters by stem, diffs against curated ids, and (if there's a diff) builds and publishes an event.
- **Per-provider failure isolation**: if fetching or parsing a given provider's live model list fails (missing key, HTTP error, timeout, unexpected response shape), that failure is logged and only that provider's check is skipped for the run — the task continues to the next provider rather than raising and failing the whole run.
- **Event publishing**: follows the existing `create_mcp_server_command` / `build_mcp_server_created_event` pattern — a new `app/events/provider_model_events.py` module with a builder function producing a CloudEvents-shaped `Event` (via `tessera_sdk`), and the task publishes it with `NatsEventPublisher().publish_sync(event, event.event_type)`. Two event types are introduced (e.g. `provider_model.added`, `provider_model.removed`), one event per provider per direction that has a non-empty diff (no event is published when a provider's check finds no drift). The event payload includes the provider id and the list of affected model ids (plus `created_at` for additions where a "newer version" was detected).
- **Publish failure handling**: matches existing precedent exactly — publish is wrapped in try/except, failures are logged (`logger.exception`) and swallowed, not retried or escalated. This is an accepted limitation carried over from `create_mcp_server_command`, not something this PRD changes.
- **No code auto-update**: the task never writes to `_models`, never opens a PR, and never touches the adapter files. Its only output is the NATS event; a human does the rest.
- **New adapter interface addition**: `list_models()` remains the curated, human-maintained list used by `GET /providers`; `fetch_live_model_ids()` (or similarly named) is purely for the drift check and is never exposed through the public API.

## Testing Decisions

Good tests here exercise externally observable behavior — what diff a given (curated list, live list) pair produces, and what gets published — not internal call sequencing inside the task.

- **Diffing logic**: unit test the stem-filtering + diff computation as a standalone function/helper (curated ids + live `[{id, created_at}]` in, `added` / `removed` / "newer" out) with fabricated inputs covering: no drift, pure addition, pure removal, both at once, and a live id outside all stems (must be excluded). No HTTP or Celery required — this is the one piece of new logic most worth isolating and testing thoroughly, similar in spirit to the `TextPart`-joining helper extracted in PRD 0017.
- **Adapter `fetch_live_model_ids()`**: unit test each adapter's implementation with a mocked HTTP response, asserting it correctly maps the provider's raw JSON shape into `{id, created_at}` pairs, and that a non-2xx/network error raises (so the task's per-provider try/except has something real to catch).
- **The Celery task**: add a new test module under `tests/app/tasks/` (following the existing `test_log_completion_usage.py` pattern) that mocks `fetch_live_model_ids()` per adapter and a `NatsEventPublisher`, and asserts: an event is published only when there's a real diff, the event payload contains the right provider id and model ids, and a failure from one adapter's fetch doesn't prevent the other adapter from being checked or its event from being published.
- **Event builder**: unit test `build_provider_model_*_event()` the same way `build_mcp_server_created_event` would be tested (if such a test exists) — asserting the constructed `Event`'s `event_type` and `event_data` shape, without needing a real NATS connection.
- No router/integration test is needed since this feature has no HTTP-facing endpoint.

## Out of Scope

- Auto-updating `_models` in code, or opening a PR automatically — a human always adds the reviewed entry.
- Real-time or webhook-based detection — this is weekly polling only.
- Persisting historical snapshots of provider model lists in a new table.
- A general multi-modal `category` field or taxonomy on `ProviderModelSchema` (deferred until modela actually adds non-chat-completion support).
- Pricing / `cost_tier` data — tracked as separate, already-in-progress work on `ProviderModelSchema`, unrelated to catalog drift detection.
- Fixing the fire-and-forget nature of NATS publish failures — this PRD reuses the existing swallow-and-log precedent as-is.
- Any new deploy/infrastructure work — `modela-beat` is already running in production; only the in-code schedule is new.

## Further Notes

- If a third provider adapter is added later, it only needs to implement `fetch_live_model_ids()` and choose its own family-stem tuple to be covered by this same weekly task — no changes to the task itself should be required.
- The family-stem list per adapter is a manually curated constant, not derived dynamically; if a provider renames a product line entirely (a genuinely new prefix, not a version bump on an existing one), a human will need to update the stem tuple before the check can see it — this is an inherent limit of a prefix-based allowlist and is accepted as a rare, low-cost manual step rather than solved generically.
- If modela later adds non-chat-completion support (embeddings, audio), the category question should be revisited then, informed by whatever that feature actually needs rather than guessed at now.
