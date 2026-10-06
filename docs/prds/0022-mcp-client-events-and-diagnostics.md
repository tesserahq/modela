## Problem Statement

Modela executes MCP tools inside the Chat Completions agent loop, but portals, mobile applications, and direct API customers cannot observe the application-level effects of those executions. If a user asks the model to create a person, the model may successfully invoke the Linden MCP tool, yet a person listing has no stable signal telling it to refresh. The only response visible to the application is assistant text.

MCP servers also constitute a customer-facing interface to the underlying products. An authorized customer calling a Linden MCP tool directly must continue receiving the complete resource representation, just as an authorized HTTP API caller does. Reducing normal MCP results to UI-safe projections would break that capability and make MCP a weaker interface than the HTTP API.

Application integration and diagnostic visibility are related but distinct needs. Product clients need stable, versioned facts such as “a person was created.” Debugging clients need tool name, status, duration, and an intentional diagnostic projection. Neither client should receive arbitrary tool arguments or results merely because Modela can see them internally.

The system needs a standardized MCP result convention that preserves full normal tool responses while adding existing Tessera/Linden domain events and safe diagnostics as explicit metadata. Modela must consume these channels independently and expose them through additive, opt-in Chat Completions extensions without changing what the model sees or what direct MCP customers receive. The same event may be delivered inline through MCP/Chat Completions and later through NATS; its identity and domain semantics must remain stable so applications can react immediately and deduplicate later delivery. The mutation that produces an event must be atomic, and the portals and mobile application must consume the event; transport alone does not deliver the intended integrated experience.

The current Tessera ecosystem is controlled by the same engineering organization: backend services and MCP providers are Python/FastAPI applications, shared backend contracts live in tessera-sdk, and browser applications are React clients. This event and diagnostic contract is platform-level rather than Linden-specific, but this PRD builds for those concrete consumers. A separate plugin PRD may reuse these Python contracts when plugin work begins; this feature does not build plugin certification, cross-language schemas, or compatibility machinery without an active consumer.

### Current-platform scope discipline

- Implement the smallest durable interface required by Modela, conversa, Linden, tessera-sdk, and the React clients in this rollout.
- Keep modules extensible through typed Python interfaces, clear ownership, additive fields, and transport-independent domain semantics—not through unused adapters, generators, registries, or alternate representations.
- Do not add an abstraction solely because a future provider, language, transport, or plugin might need it. A new capability is introduced when an approved PRD names a concrete consumer and acceptance path.
- Controlled Python services import tessera-sdk models and validators directly. React clients consume the typed Chat Completions and Tessera event payloads exposed by their backend boundary.
- Planned plugin work remains separate. It must evaluate the contracts that exist when implementation starts instead of forcing this PRD to predict its packaging or conformance needs.

## Solution

Standardize controlled MCP mutation tools on FastMCP's native result separation:

- `structuredContent` remains the complete normal MCP result. It is available to authorized direct MCP clients and becomes the value returned to the model during the agent loop.
- `_meta.events` contains stable Tessera `Event` objects intentionally produced by the tool. These use the same schema, domain-specific event types, and event identity as Linden events published through NATS.
- `_meta.debug` contains an optional diagnostic projection intentionally produced by the tool. It is never inferred from the complete arguments or result.

On the wire, both metadata keys are namespaced as `_meta["com.tesserahq/events"]` and `_meta["com.tesserahq/debug"]`. That prevents collisions with FastMCP's own `_meta.fastmcp` and with third-party conventions. This document uses `_meta.events` and `_meta.debug` as shorthand. Modela recognizes these keys from any configured MCP provider and accepts their values only when they pass the SDK-owned validation, version, and size rules.

Read-only tools do not need to change unless they have a meaningful domain event or diagnostic projection. Mutation tools add metadata without reducing or reshaping their normal result. Legacy tools that return ordinary values and no metadata remain compatible.

`POST /chat/completions` gains two independent opt-in response channels:

- `include: ["events"]` exposes validated Tessera events to authorized application clients.
- `include: ["tool_executions"]` exposes tool lifecycle metadata and the MCP-provided diagnostic projection to callers with a dedicated diagnostic permission.

Callers may request either channel, both channels, or neither. Modela sends only the complete normal result back to the LLM. It validates, limits, and emits metadata separately. Invalid metadata is dropped and logged without changing tool execution or the agent-visible result.

The Linden portal and mobile app do not call Modela directly. They talk to conversa, which calls Modela through the tessera-sdk `ModelaClient`. Today conversa forwards only assistant text, and the SDK can neither request extensions nor keep them in its response models. This PRD therefore covers five components:

- **Modela** produces the extension channels.
- **tessera-sdk** lets callers request the channels and keeps them in parsed chunks and responses.
- **conversa** requests `events` from Modela and passes them through its own `/chat/completions` stream and response, so the Linden portal and mobile app can receive them.
- **Linden portal** consumes domain events and invalidates the affected account-scoped caches.
- **Linden mobile app** consumes the same domain events and invalidates its corresponding local data.

The user-facing outcome (stories 1–2) is delivered only once all three ship.

This PRD supersedes PRD 0021's proposal for Modela to derive exposed argument and result fields from arbitrary tool payloads. It retains the useful lifecycle, bounding, compatibility, and authorization decisions while moving responsibility for public-safe domain events and debug-safe projections to the MCP tool that understands the domain.

Implementation is not limited to adding fields at existing call sites. Before changing code, each affected repository must identify the current event-construction, transaction, MCP-result, streaming, and client-consumption paths and define the durable module seams used by the feature. Adjacent refactoring that removes duplication, restores a single source of truth, clarifies ownership, or makes those seams testable is part of the feature. Refactoring must preserve observable behavior outside the contracts deliberately changed by this PRD and must be delivered in reviewable increments.

## User Stories

1. As a portal user, I want a person listing to refresh after the model creates a person, so that the interface reflects the completed action immediately.
2. As a mobile user, I want model-driven changes to appear without leaving and reopening the screen, so that conversational actions feel integrated with the application.
3. As a customer using an MCP server directly, I want the complete authorized tool result, so that MCP remains a full interface to product resources.
4. As a customer using an MCP server directly, I want existing read tools to retain their response content, so that adopting event metadata does not break my integration.
5. As a customer using an MCP server directly, I want mutation tools to retain their complete response content, so that metadata does not replace the normal result.
6. As an application developer, I want existing domain events such as `person.created`, so that I can refresh the relevant collection without parsing assistant prose or learning a second event vocabulary.
7. As an application developer, I want stable update and deletion events, so that local caches can reconcile model-driven mutations.
8. As an application developer, I want events to identify the affected resource type and ID, so that I can update the correct cache entries.
9. As an application developer, I want events to identify related resources such as an account, so that I can scope collection invalidation correctly.
10. As an application developer, I want public-safe `event_data` with the affected resource and related-resource IDs, so that I can reconcile the interface without exposing the complete resource.
11. As an application developer, I want the existing Tessera `Event` schema and its `dataschema` support, so that clients can evolve without relying on tool-specific result shapes.
12. As an application developer, I want domain events independent of frontend cache-library keys, so that web and mobile clients can react using their own state-management implementations.
13. As an API customer, I want domain events to be opt-in, so that ordinary completion responses remain unchanged.
14. As an API customer, I want malformed event metadata ignored without losing the assistant response, so that an MCP metadata defect does not break inference.
15. As a support engineer, I want to see which tool ran, so that I can diagnose unexpected model behavior.
16. As a support engineer, I want tool status and duration, so that I can distinguish tool failures from slow model responses.
17. As a support engineer, I want a tool-authored diagnostic projection, so that I receive useful context without arbitrary private fields.
18. As a security owner, I want tools to choose diagnostic fields deliberately, so that Modela never publishes complete arguments or results by default.
19. As a security owner, I want diagnostic traces protected by a dedicated permission, so that ordinary completion access does not imply debugging access.
20. As a ModelConfig owner, I want to enable domain events and diagnostics independently, so that stable integrations do not require enabling privileged traces.
21. As a model developer, I want the complete normal tool result returned to the LLM, so that metadata support does not reduce the model's ability to complete its task.
22. As a model developer, I want metadata excluded from the agent-visible result, so that UI instructions and diagnostic details do not affect model reasoning.
23. As an MCP developer, I want one shared helper for producing compliant results, so that each tool does not reimplement the envelope.
24. As an MCP developer, I want typed event and diagnostic models validated before transmission, so that errors are caught close to their source.
25. As a maintainer, I want legacy MCP tools without metadata to continue working, so that migration can be incremental.
26. As a maintainer, I want Modela to use FastMCP's native `structuredContent` and `_meta` fields, so that the design remains compatible with the MCP protocol.
27. As a platform operator, I want event and trace counts and sizes bounded, so that a tool or looping agent cannot produce unbounded responses.
28. As a portal developer, I want open tool calls reconciled when an SSE stream terminates unexpectedly, so that the UI does not display a permanently running operation.
29. As a business owner, I want the same Tessera domain-event vocabulary across MCP, Chat Completions, NATS, web, and mobile, so that each application needs only one event integration.
30. As a customer developer, I want published documentation for the exposed domain-event contract, so that direct Chat Completions integrations can respond to model-driven changes safely.
31. As a conversa developer, I want the tessera-sdk `ModelaClient` to request extension channels and expose them on parsed chunks and responses, so that conversa does not parse raw SSE to obtain domain events.
32. As a Linden portal or mobile developer, I want conversa to forward Modela domain events in its own chat stream, so that the application receives them through the chat API it already uses.
33. As a platform administrator, I want metadata from every MCP provider validated against the SDK-owned contract, so that malformed or unsupported metadata cannot enter completion responses.
34. As a portal user, I want the interface to reflect a completed mutation even when the model's subsequent response fails, so that I do not retry and create a duplicate.
35. As a direct MCP customer, I want a tool's advertised output schema to stay the same when it adopts metadata, so that typed integrations keep working.
36. As a portal user, I want the person and reminder listings to reconcile all effects of creating a person with a birthday, so that related automatic mutations are not left stale.
37. As an application developer, I want one mutation outcome to create one domain event per durable effect and preserve that event across delivery transports, so that inline and NATS representations cannot drift independently.
38. As an API customer, I want committed domain events included when a later non-streaming model round fails, so that I know which collections to reconcile before retrying.
39. As a security owner, I want exposed `event_data` to follow a strict reviewed schema, so that a tool cannot accidentally expose arbitrary resource fields.
40. As an MCP provider developer, I want valid SDK-conforming metadata accepted without a separate manual trust flag, so that registering a controlled provider is sufficient and metadata cannot be silently disabled by missed configuration.
41. As an application developer, I want repeated delivery of the same event through Chat Completions and NATS to preserve `source` and `id`, so that I can deduplicate it reliably.
42. As an application developer, I want MCP-originated mutations marked with the existing `tags` field, so that I can identify their origin without changing the shared Tessera event schema.
43. As a maintainer, I want event construction, validation, collection, and transport concerns owned by deep modules with small interfaces, so that adding another domain event or delivery adapter does not require coordinated edits throughout the agent loop.
44. As a maintainer, I want obsolete and duplicate event-projection paths removed during migration, so that the implementation has one source of truth rather than permanent compatibility layers.
45. As a reviewer, I want behavior-preserving refactors separated from contract changes where practical, so that architectural improvements and product behavior can be verified independently.
46. As a framework maintainer, I want reusable event, completion-extension, diagnostic, and metadata contracts owned by tessera-sdk, so that Modela, conversa, and controlled Python MCP servers do not maintain parallel definitions.

## Implementation Decisions

### Engineering quality and module design

- Every repository change begins with a short implementation design that maps the current call path, identifies ownership, lists affected interfaces and invariants, and names the tests that protect existing behavior. Coding does not begin from the PRD alone when repository-specific behavior remains ambiguous.
- The implementation favors deep modules: a small interface hides event validation, origin-tag enforcement, size limits, serialization, collection, and error handling. Callers provide domain facts or an existing `Event`; they do not repeat wire-key selection, validation branches, or transport-specific formatting.
- The primary seams are: Linden mutation outcome to Tessera event construction; MCP result to validated Modela execution result; execution result to Chat Completions extensions; and Tessera event to portal/mobile cache reconciliation. Each seam has a typed interface and contract tests. Adapters may vary by transport, but event semantics do not.
- Event construction has one owner. Code must not independently build equivalent MCP and NATS events, copy event dictionaries between layers, or reconstruct events from tool arguments after execution. A single constructed `Event` flows to the required delivery adapters.
- Transport adapters remain thin and policy-free. MCP metadata, Chat Completions SSE, non-streaming JSON, conversa forwarding, and existing NATS publication serialize or forward the event; they do not redefine event types, origin, relationships, or disclosure policy.
- Existing helpers and modules are evaluated before adding new abstractions. A new module or seam is introduced only when it concentrates behavior used by multiple callers or enables a real alternative adapter. Pass-through wrappers and one-off abstractions are rejected.
- Reusable contracts belong in tessera-sdk when at least two repositories in this rollout consume the same semantics. Those models, enums, constants, validators, serializers, parsers, fixtures, or helpers are defined once and imported by consumers. Repositories must not copy SDK models into local equivalents merely to avoid an SDK release.
- The sharing test is based on semantics, not identical syntax. Code belongs in tessera-sdk when its meaning is product-independent and stable across callers. Product-specific domain rules, database transactions, authorization policy, cache invalidation, and transport wiring remain in their owning repositories even when their implementations look similar.
- Adjacent refactoring is required when the touched code has duplicated event construction, mixed transaction and serialization responsibilities, transport knowledge inside domain commands, untyped dictionary plumbing, misleading names, or dead compatibility paths that would otherwise be extended by this feature.
- Refactoring uses replace-then-delete rather than indefinite layering. Once callers move to the new interface and compatibility is no longer required, obsolete projectors, helpers, branches, and tests are removed in the same rollout or in an explicitly linked blocking issue with an owner and removal condition.
- Public interfaces are typed and documented with their invariants, ordering, error behavior, limits, and performance expectations. Internal implementation details remain private so tests and callers do not couple to them.
- The event path must not add network calls, persistence operations, or repeated serialization to the synchronous LLM critical path. Validation and serialization occur at most once per delivery representation, collectors are bounded, and the opted-out path performs no event projection or retention beyond processing the normal MCP result.
- Refactors must not silently broaden the feature. Cleanup in directly affected paths is in scope; unrelated repository-wide rewrites require a separate issue. Any deferred cleanup that would compromise correctness, security, performance, or a single source of truth blocks rollout rather than becoming optional debt.
- Each repository's pull request describes the resulting module seams, removed duplication, compatibility decisions, and any deliberately deferred work. Names use domain language (`Event`, `MutationEffect`, `ToolExecution`) rather than provider or product names that may change.

### Event and transport contract

One event is constructed for each committed domain effect and then delivered through multiple adapters without changing its identity or semantics:

```text
MutationEffect
    -> Tessera Event
        -> NATS publisher
        -> MCP metadata
            -> Modela collector
                -> streaming or non-streaming Chat Completions extension
                    -> conversa
                        -> portal/mobile event adapter
```

#### Events versus tool executions

The Chat Completions endpoint exposes two independent channels because they describe different facts and serve different consumers:

| Channel | Question answered | Intended consumers |
| --- | --- | --- |
| `events` | What durably changed in the product? | Portal, mobile applications, and customer integrations |
| `tool_executions` | What did the model attempt to execute, and how did it complete? | Developers, support engineers, and diagnostic tooling |

An event is a committed domain fact represented by the existing Tessera `Event` contract. It may also be published through NATS and is suitable for application reactions such as cache invalidation:

```json
{
  "id": "event_123",
  "source": "/linden/persons",
  "spec_version": "1.0",
  "event_type": "person.created",
  "subject": "/persons/person_123",
  "tags": ["origin:mcp"],
  "event_data": {
    "resource": {
      "type": "person",
      "id": "person_123"
    },
    "account_id": "account_456"
  }
}
```

A tool execution is an operational record of an LLM tool call. It reports lifecycle, timing, and an optional intentionally sanitized diagnostic projection; it does not assert that a domain mutation committed and is not published to NATS as a domain event:

```json
{
  "call_id": "call_123",
  "tool_name": "linden.create_person",
  "status": "completed",
  "duration_ms": 184,
  "debug": {
    "arguments": {
      "account_id": "account_456"
    },
    "result": {
      "person_id": "person_123"
    }
  }
}
```

One tool execution produces zero, one, or multiple domain events:

| Tool outcome | Tool execution | Domain events |
| --- | --- | --- |
| `list_people` succeeds | `completed` | None |
| `create_person` succeeds | `completed` | `person.created` |
| `create_person` with a birthday succeeds | `completed` | `person.created`, `reminder.created` |
| `create_person` fails before commit | `failed` | None |
| A tool commits, but a later LLM round fails | `completed` | Committed events remain valid and are returned on the supported error path |

Tool execution lifecycle and domain-event production are correlated but independent:

```text
Tool execution starts
    -> tool runs
        -> zero or more domain mutations commit
            -> zero or more Tessera events are produced
    -> tool execution completes or fails
```

Applications normally request `include: ["events"]`. Authorized diagnostic callers may request `include: ["tool_executions"]`, and callers that need both perspectives may request both. A completed tool execution is never treated as evidence of a domain mutation without a corresponding domain event.

#### MCP result compatibility

- The complete normal MCP result remains the source of truth for direct MCP callers and for the LLM. This PRD does not replace it with a public projection.
- Controlled MCP tools use FastMCP `ToolResult` when metadata is needed. The tool places its existing complete result in `structured_content` and additive metadata in `meta`, which FastMCP transports as MCP `_meta`.
- When `ToolResult` is constructed without explicit content, FastMCP derives ordinary content from `structured_content`. Contract tests must nevertheless verify equivalence for the actual supported MCP clients before migrating tools.
- Returning `ToolResult` must not change a tool's advertised schema. FastMCP derives `outputSchema` from the return annotation: `-> dict` advertises `{type: object, additionalProperties: true}`, while `-> ToolResult` advertises none (verified with FastMCP 3.4.7). Migrated tools therefore declare their previous schema explicitly (`@tool(output_schema=...)`), and the shared result module provides a decorator or helper that does this, so that `tools/list` is identical before and after migration.

#### Canonical event vocabulary and identity

- There is one domain-event vocabulary and one Tessera `Event` structure across Linden, MCP metadata, Chat Completions, NATS, conversa, web, and mobile. Event types remain domain-specific (`person.created`, `person.updated`, `person.deleted`, `reminder.created`, and so on). This PRD does not introduce the parallel generic vocabulary `resource.created`, `resource.updated`, or `resource.deleted`.
- The event contract is the existing `tessera_sdk.infra.events.event.Event` schema: `id`, `source`, `spec_version`, `event_type`, `data_content_type`, `dataschema`, `subject`, `time`, `event_data`, `user_id`, `labels`, `tags`, `project_id`, and `privy`. Exposed events use these actual serialized field names. This PRD does not require renaming them to the canonical CloudEvents JSON attribute names.
- The same domain occurrence preserves `id`, `source`, `spec_version`, `event_type`, `subject`, `time`, `dataschema`, and `tags` whether delivered inline through MCP/Chat Completions or asynchronously through NATS. Clients identify duplicate delivery by the tuple `(source, id)`.
- `source` identifies the event-producing domain context; it does not identify the delivery transport. The system must not produce separate `/mcp` and `/nats` sources for copies of the same occurrence, because doing so would defeat CloudEvents-compatible deduplication.
- Mutation origin uses the existing `tags: list[str]` field. `origin:*` is a reserved tag namespace, and new events contain exactly one origin tag. MCP-initiated commands use `origin:mcp`; other initially recognized values are `origin:http-api`, `origin:scheduled-job`, and `origin:import`. Unknown origin values and unrelated tags are preserved and ignored by consumers that do not understand them. Tags are informational routing and diagnostic metadata and must never be used as an authorization boundary.

#### Event production and transaction integrity

- Migrated mutation commands return a typed `MutationOutcome[T]` containing the primary value and an ordered list of typed `MutationEffect` records. Each effect contains the action, internal resource reference, related references, changed field names, and the domain objects needed by the existing Tessera event builders. REST, MCP, and other command callers are updated to consume `outcome.value`. Each effect is converted to a Tessera `Event` once; the same event object is used for MCP metadata and NATS publication rather than reconstructing separate events from request arguments or serialized resources.
- Commands record every durable resource effect in the outcome, including automatic secondary mutations. Creating a person with a birthday therefore records both the person creation and the birthday-reminder creation, with their stable IDs. Updating or deleting a birthday records reminder effects when the command creates, updates, or deletes the associated reminder.
- Read-only tools remain unchanged by default. Mutation tools add metadata when they can state a durable application effect.
- A shared MCP result module validates Tessera `Event` objects and defines the helper used to construct metadata-bearing results plus the `ToolDebug` model. This is a deep module: individual tools provide domain facts, while the module owns validation, serialization, limits, origin-tag validation, and wire naming.
- A synchronous mutation emits success events only after the whole command is durably successful. Migrated repositories do not call `commit()`; they use `flush()` when generated IDs or defaults are needed, and the managed `session_scope` performs the single root commit after all primary and secondary mutations succeed. Existing repository-level commits in a candidate command path are a migration blocker and must be removed before that tool emits domain events. A commit failure prevents the MCP result and its metadata from being returned.
- The person-create and person-update command paths are part of this PRD's first migration. Their person repository writes are changed from `commit()` to `flush()`, and all reminder mutations used by those commands participate in the same managed transaction. Tests prove that failure after the person write leaves neither the person nor its secondary reminders committed.
- A tool that only accepts or queues asynchronous work does not emit a completed domain event such as `person.created` prematurely. This PRD defines no operation ID, operation result, queued-work event, status endpoint, progress protocol, or completion protocol. Such a tool returns only its pre-existing normal MCP result and emits no domain event through this feature until the underlying domain mutation has actually committed.
- Failed tools emit no success domain events. MCP `isError` and raised tool errors remain normal MCP failure mechanisms.

#### Public event data and diagnostics

- Customer-exposed `event_data` is a reviewed, public-safe event contract containing resource IDs, related resource IDs, and changed field names needed for reconciliation. It never contains the domain resource's complete representation merely because the internal event builder has access to it. When existing NATS events contain broader or sensitive `event_data`, that event type must be migrated to a safe common contract or separated onto an internal-only authorized subject before it can be exposed to Chat Completions or customer application streams.
- Public event payloads identify resources with stable singular types such as `person`, `account`, `pet`, and `reminder`; they do not expose Python class names, database table names, frontend cache keys, or UI commands.
- Domain events state completed facts. Tools never emit instructions such as “refresh this page,” navigation destinations, React Query keys, or mobile store actions. Each application maps `event_type`, `subject`, and safe `event_data` to its own cache invalidation and interface behavior.
- `_meta.debug` is an optional, tool-authored projection with separate `arguments` and `result` objects. Absence of `debug` means no argument or result payload is available for diagnostics.
- Debug projections contain only fields intentionally selected by the tool author. Modela never falls back to the original arguments, `structuredContent`, ordinary content, exception text, or transport data.
- Sensitive values such as credentials, authorization headers, tokens, email addresses, phone numbers, birthdays, free-form notes, and complete resource documents are excluded from debug projections unless a separate reviewed requirement explicitly permits a particular field.
- Debug projection schemas are intentionally permissive enough to support different tools but are subject to central depth, item-count, and byte limits. Common secret patterns are redacted as defense in depth, not as the primary disclosure control.

#### Modela ingestion and metadata validation

- Modela's MCP executor returns an internal typed result containing `agent_value`, validated `events`, validated `debug`, execution status, and optional error category. `agent_value` is derived from the normal MCP result; metadata never replaces it.
- Modela's MCP toolset records the typed metadata in a request-scoped observer and returns only `agent_value` to pydantic-ai.
- Legacy MCP results without `_meta` produce the same agent value as today, no domain events, and no diagnostic projection.
- A configured MCP provider requires no separate metadata enablement switch. Provider registration establishes that Modela may invoke its tools; metadata acceptance is then determined by recognized SDK-owned keys, SDK model validation, channel limits, request opt-in, ModelConfig exposure policy, and diagnostic authorization.
- Modela validates the generic Tessera event envelope but does not maintain an allowlist of every domain `event_type`. Valid events with unknown domain types may be transported; each consuming application handles only the event types and `event_data` contracts it understands and safely ignores the rest.
- Invalid or unsupported metadata is dropped and logged with tool identity and validation errors, without logging rejected payload values and without failing the agent run.

#### Chat Completions access and authorization

- The Chat Completions request schema gains an optional top-level `include` collection. Supported values introduced by this PRD are `events` and `tool_executions`. Unsupported values return `422` with useful validation detail.
- OpenAI SDK users pass these extension fields through `extra_body`, which the OpenAI SDK merges into the top-level request.
- The endpoint's `extra_body` field is not legacy. tessera-sdk's `ChatCompletionRequest` declares it, and `ModelaClient.complete()`/`stream_complete()` send it as a literal nested key. Modela therefore accepts `extra_body.include` as an alias for top-level `include` and merges the two. A `422` is returned only when both are present with different values, or when either contains an unsupported value. This keeps existing SDK versions working while the SDK moves to a first-class `include` parameter.
- `events` and `tool_executions` are independently selectable. Requesting both does not duplicate event data inside the diagnostic trace.
- ModelConfig gains independent `expose_events` and `expose_tool_executions` booleans, both defaulting to `false` for existing configs. Requests for a disabled channel return `403` before MCP catalog loading or inference.
- All completion requests require the existing completion `create` permission, which the endpoint currently constructs but does not apply.
- Domain events require completion `create` permission and ModelConfig consent. Diagnostic traces additionally require a dedicated `inspect_tool_executions` action on the `modela.completion` resource.
- Modela has no real project scoping for completions today: `infer_project` returns the caller-supplied `project_id` query parameter (default `*`), and ModelConfig has no `project_id` (slugs are globally unique). The diagnostic permission is therefore checked at the global domain (`*`, via `infer_domain`), not at a caller-chosen project. A grant scoped to one project must not be able to inspect another project's configs. Project-scoped diagnostics can be introduced once ModelConfig carries a project.
- Modela uses its existing RBAC authorization capabilities to require the permission string `modela.completion:inspect_tool_executions`; this feature does not add a new RBAC framework action, dependency mechanism, or Custos code path. Before diagnostics are enabled, an operator manually creates the permission and assigns it to the intended platform support/diagnostics role in Custos. End-user and project-member roles do not receive this permission.

#### Delivery, failure handling, and performance

- Streaming domain events use valid Chat Completions chunk envelopes with `choices: []` and one `extensions.event` Tessera `Event` object. Events are emitted after the corresponding successful tool result is received and validated.
- Streaming diagnostic lifecycle records use the same chunk envelope with `extensions.tool_execution`. A started record contains sequence, call ID, and qualified tool name. A completed record contains sequence, call ID, qualified tool name, status, duration, and the optional MCP-provided debug projection.
- Started diagnostic records do not expose raw arguments. The safe debug argument projection becomes available only on completion because it is supplied in MCP result metadata.
- Non-streaming responses use `extensions.events` and `extensions.tool_executions`, each an ordered array. An enabled and requested channel with no records returns an empty array.
- When neither channel is requested, `extensions` is omitted and existing response bodies remain unchanged.
- Domain events describe mutations that have already been committed, so they survive a later failure of the run. The completion layer owns a request-independent `CompletionRunContext` containing the bounded event collector. If inference fails after collecting events, the command raises a typed `CompletionRunError` containing the original provider/error classification and an immutable snapshot of validated events. HTTP exception handlers serialize the original status and detail plus `extensions.events` when the channel was requested and permitted. Non-HTTP callers can inspect the same typed error without depending on request state. This applies to provider errors, provider timeouts, structured-output failures, and unexpected failures after a committed mutation. Diagnostic records are not attached to error bodies. Clients should still treat any completion error as a reason to reconcile affected collections, because events are best-effort.
- Domain-event and diagnostic delivery is best-effort on streaming transport failure. If the stream terminates with open calls, clients mark them `aborted` or `unknown`; the server emits aborted records only when it detects the failure while the stream remains writable.
- Modela enforces fully independent count and serialized-size budgets per channel, so enabling diagnostics can never suppress domain events. Initial defaults: `events` allows 100 events and 256 KiB; `tool_executions` allows 100 diagnostic records and 1 MiB. These are record budgets only. They never stop, skip, or delay tool execution, which remains governed by existing agent behavior. At most one truncation marker is emitted per channel, after which further records for that channel are suppressed and not retained in memory.
- Metadata is response-only under this PRD. Persistence, replay, retention, and historical event delivery remain separate work.
- The normal MCP result may contain data a direct MCP customer is authorized to access but that must never appear in a Chat Completions extension. Tests treat this separation as a security invariant.
- The first controlled-server rollout covers person creation and update. A person creation event identifies the person and related account; a person update event identifies the person, related account, and names of changed fields without including their sensitive values.
- Listing and get-by-ID tools do not emit mutation events. Their complete normal results remain unchanged.
- Migration is incremental. Modela ships support for metadata-free legacy tools, then controlled MCP mutation tools adopt the shared result module one group at a time.

### tessera-sdk (`ModelaClient`)

- tessera-sdk is the source of truth for reusable contracts introduced or extended by this feature. At minimum it owns:
  - the existing `Event` model and its serialization behavior;
  - reserved origin-tag constants and helpers to add, replace, parse, and validate the single `origin:*` tag;
  - namespaced MCP metadata-key constants for `com.tesserahq/events` and `com.tesserahq/debug`;
  - typed public-safe event-data primitives that are genuinely cross-product, such as resource references and changed-field collections;
  - `ToolDebug`, tool-execution lifecycle records, statuses, and truncation-marker wire models;
  - the supported completion `include` values and typed `event`/`events` and `tool_execution`/`tool_executions` extension models;
  - parsers and serializers for streaming and non-streaming extension envelopes where their behavior is transport-independent;
  - representative JSON fixtures used by the SDK parser tests when a file is clearer than an inline Python value.
- Controlled Python MCP providers use the SDK models, constants, and helpers directly. This PRD does not publish a separate JSON Schema, generated client package, provider certification suite, or cross-language contract layer.
- Provider repositories protect their real MCP behavior with integration tests: normal results and advertised output schemas remain unchanged when metadata is added, and domain-owned event payload tests prove sensitive fields are absent.
- SDK interfaces must not depend on Modela, conversa, Linden, a frontend cache library, or a specific MCP server. Optional protocol adapters may live in clearly separated SDK modules and may use optional dependencies, but importing the core event and completion models must not install FastMCP or application frameworks.
- Domain-specific `event_data` models live in tessera-sdk only when they are part of a Tessera-wide public contract with at least two real consumers. Linden-only payload construction and business validation remain in Linden, but must compose SDK primitives rather than redefine them.
- `MutationOutcome` and `MutationEffect` move to tessera-sdk only if their interface proves product-independent during the implementation design and has at least two concrete consumers. Until then, they remain owned by the domain repository; speculative generalization is not a reason to expand the SDK interface.
- Server-side authorization, ModelConfig exposure policy, collection budgets, transaction management, NATS publication, and UI cache behavior remain implementations in their owning repositories. The SDK may define their shared wire values but does not own operational policy.
- A shared contract change lands and releases in tessera-sdk before dependent repository changes. Temporary local copies are prohibited. Consumers declare an explicit minimum SDK version and remove superseded local types as part of the same migration.
- SDK additions follow semantic versioning. Backward-compatible optional fields and event types receive a compatible release; breaking model or serialization changes require an intentional major-version migration plan.
- `ModelaClient.complete()` and `stream_complete()` gain an `include: list[str] | None` parameter, sent as top-level `include`. The existing `extra_body` parameter keeps its current nested wire behavior for compatibility.
- `ChatCompletionChunk` and `ChatCompletionResponse` gain an optional `extensions` field with typed `event`/`events` and `tool_execution`/`tool_executions` members. The event members use the existing tessera-sdk `Event` model rather than defining another event class. Today both completion models drop unknown fields because pydantic's default is `extra="ignore"`, so without this change the SDK silently discards every extension.
- Event consumers branch on `event_type` and tolerate domain event types they do not recognize. Schema evolution uses the existing `spec_version` and optional `dataschema` fields rather than a second event version field.
- The SDK's streaming iterator yields chunks with `choices: []` unchanged. Callers that read only text must keep skipping them, as conversa does today.
- When a request fails, the SDK exception exposes any `extensions.events` from the error body, so a caller can reconcile mutations committed before the failure.

### conversa

- conversa is the only path from the Linden portal and mobile app to Modela. `linden-portal` uses `conversa-chat-transport.ts`, and conversa calls Modela through `ModelaClient` with the end user's delegated token.
- conversa's own `/chat/completions` gains an opt-in `include: ["events"]`. Only when its caller opts in does conversa request `events` from Modela.
- The worker's Modela stream (`app/workers/llm.py`) currently yields only text and skips every `choices: []` chunk. It changes to yield a small typed union, either a text delta or a Tessera event. The SSE renderer in `app/routers/chat_router.py` emits events as `choices: []` chunks with `extensions.event`, in the order received, interleaved with text. This is the same envelope Modela uses, so one client parser works against either service.
- conversa's non-streaming response includes `extensions.events`, and a conversa error response carries the events Modela returned in its error body.
- conversa forwards only `events`. It never requests or forwards `tool_executions`: diagnostics are for direct Modela inspection by holders of `inspect_tool_executions` and are not exposed to end-user applications.
- conversa does not persist events in session history. Channels that cannot consume them (for example the Telegram workflow) do not request them.
- The ModelConfig that conversa uses (currently the default chat config, since it sends no `model`) must have `expose_events` enabled. Linden event metadata is accepted automatically when it conforms to the SDK-owned contract.

### Linden portal and mobile app

- Both applications add one Tessera-event adapter at their chat transport seam. The adapter accepts the same `Event` structure used by NATS and maps `event_type`, `subject`, and public-safe `event_data` to the application's existing cache/store invalidation operations; chat views do not implement resource-specific branching themselves.
- The first rollout handles `person.*` and `reminder.*` event types related to an account. A person create, update, or delete invalidates the affected account's person collection and the individual person entry when present. A reminder create, update, or delete invalidates the affected account's reminder collection and individual reminder entry when present.
- Applications use the account reference in `event_data` or existing labels to scope invalidation. An event without the required account relationship is ignored and recorded as a schema/contract error; it never triggers a global cache flush.
- Domain events may arrive before, between, or after text chunks. Applications process each event immediately and independently of rendering assistant text.
- Applications retain a bounded deduplication cache keyed by `(source, id)`. If an event is handled immediately from Chat Completions and later arrives through the NATS-backed application event stream, the second delivery does not repeat the invalidation. Reactions remain idempotent cache invalidations rather than local replay of mutations; applications must not create local resources directly from event data.
- When the chat stream terminates with an error after one or more events, applications retain the invalidations already applied and surface the chat error separately. They do not undo a committed mutation or automatically retry the user request.
- Portal and mobile tests use typed event examples at the conversa API boundary, proving that person creation with a birthday invalidates both person and reminder collections. They do not consume backend parser fixtures or generated SDK schemas.

### Rollout order

Before each repository enters this rollout, its implementation design and refactoring plan are reviewed. Each step leaves the repository in a coherent state: compatibility may be temporary, but duplicate event construction and ambiguous ownership may not be the final state of any rollout step.

1. tessera-sdk defines and releases the shared Python contracts, constants, validators, representative parser fixtures, completion extension models, and `ModelaClient` support. Its release notes identify the minimum compatible version and migration path for superseded local types.
2. Modela upgrades tessera-sdk and ships extension support, the `extra_body.include` alias, the ModelConfig flags, and the diagnostic RBAC change using SDK-owned contracts. The exposure flags are default-off, so there is no behavior change.
3. conversa upgrades tessera-sdk and ships pass-through of Tessera events behind its own opt-in without defining local wire models.
4. Linden upgrades tessera-sdk; its migrated person command paths become single-transaction operations and return mutation outcomes. Each effect creates one Tessera event whose identity is preserved for MCP metadata and NATS publication.
5. Linden MCP person tools adopt the shared result module and SDK-owned metadata contracts, with `tools/list` unchanged.
6. Linden portal and mobile define their React-facing event types at the conversa API boundary and ship their Tessera-event adapters, bounded `(source, id)` deduplication, and account-scoped person/reminder invalidation mappings behind feature flags.
7. An operator manually creates `modela.completion:inspect_tool_executions` and the intended support/diagnostics role assignment in Custos, verifies the grants, and records completion in the rollout issue. Operators then enable `expose_events` on conversa's ModelConfig and the portal/mobile feature flags; no Custos deployment or per-provider metadata setting is required.

## Testing Decisions

- Tests assert observable contracts rather than private helper calls.
- Characterization tests are added before refactoring any path whose existing behavior is not already protected. Refactoring commits keep those tests green before intentional contract changes are introduced.
- Tests exercise the public interface at each module seam. They do not patch or assert private implementation steps merely to preserve the pre-refactor structure.
- Static typing, repository linting, formatting, and the complete relevant test suites are required for every affected repository; newly introduced suppressions, broad `Any` types, and unvalidated dictionaries require explicit justification in review.
- Architecture-focused tests or dependency checks prevent domain commands from importing MCP, Chat Completions, conversa, or UI transport modules and prevent delivery adapters from constructing domain events.
- A code-search verification in each migration pull request proves that obsolete generic event types, duplicate projectors, superseded metadata keys, and dead compatibility helpers have been removed when their migration step completes.
- Cross-repository contract tests import or generate from tessera-sdk-owned definitions. Tests fail if a repository introduces a second local definition for an SDK-owned wire model, metadata key, include value, status, or origin-tag convention.
- Direct MCP contract tests compare an existing dictionary result with the new metadata-bearing `ToolResult` and verify that supported clients still receive equivalent normal content, structured content, and parsed data.
- Direct MCP tests verify that complete authorized person and account representations remain available after metadata adoption.
- Direct MCP contract tests verify that `tools/list` output, including each migrated tool's `outputSchema`, is identical before and after migration.
- Tool-level tests verify that create, update, and delete mutations emit the correct Tessera domain event only after success.
- Tool-level tests verify that failed mutations and raised tool errors emit no success events.
- Transaction tests force failures after person insertion and during birthday-reminder creation and verify that neither the person nor reminder remains committed and no domain event is emitted.
- Mutation-outcome tests verify that one Tessera `Event` is constructed per ordered effect, including secondary reminder effects, and that the same `id`, `source`, `event_type`, `subject`, `time`, `dataschema`, and tags are preserved in MCP and NATS delivery.
- Origin-tag tests verify that MCP-initiated mutations contain exactly one `origin:mcp` tag, that other tags are preserved, that unknown tags are ignored by consumers, and that changing delivery from Chat Completions to NATS does not change the origin tag or `source`.
- Person-tool tests verify that create and update events contain the correct person and related account IDs.
- Person-tool tests verify that update events list changed field names without including email, phone, birthday, or other changed values.
- Read-tool regression tests verify unchanged results and absence of mutation events for listing and get-by-ID tools.
- Shared MCP result module tests cover `Event` validation, serialization into `_meta["com.tesserahq/events"]`, resource identifier normalization, origin-tag validation, field limits, and invalid metadata rejection.
- Public event-data tests verify the reviewed schema, rejection of unknown fields, and omission of sensitive or complete resource data.
- Diagnostic tests verify that only explicitly authored debug fields are present and that complete normal results are never copied automatically.
- Modela executor tests cover metadata-bearing success, metadata-free legacy success, MCP `isError`, malformed metadata, unknown versions, and payloads that exceed limits.
- Agent-loop tests verify that the LLM receives the complete normal result and never receives domain-event or debug metadata.
- Streaming tests verify domain-event ordering after successful completion, diagnostic started/completed correlation, parallel calls, empty-choice chunks, truncation markers, and final completion behavior.
- Non-streaming tests verify independent arrays, empty arrays for requested channels with no records, and omission of extensions when neither channel is requested.
- Authorization tests verify independent ModelConfig flags, ordinary completion permission for domain events, and the additional diagnostic permission for tool executions. They also verify that the permission is checked at the global domain, so a caller-supplied `project_id` cannot change the outcome.
- Metadata-validation tests verify that SDK-conforming namespaced metadata from any configured provider is accepted without a provider flag; unnamespaced keys, malformed contracts, unsupported versions, and over-limit payloads are ignored and logged without their values. Unknown but valid domain event types are transported and ignored safely by consumers that do not support them.
- Request tests verify that `extra_body.include` (as sent by the current tessera-sdk) is accepted as an alias, that matching top-level and nested values are merged, and that conflicting values return `422`.
- Error-path tests verify that a non-streaming run failing after a successful mutation returns the error status with `extensions.events` in the body, and that diagnostic records are not attached.
- Completion-error tests exercise the typed `CompletionRunError` outside HTTP and through each relevant HTTP exception handler, verifying that status classification is preserved and bounded events survive exception unwinding.
- Budget tests verify that saturating the `tool_executions` budget does not suppress any domain event.
- tessera-sdk tests verify that `include` is sent at the top level, that `extensions.event`/`events` parse as existing `Event` models, that unknown domain event types are tolerated, and that error-body events are exposed on exceptions.
- tessera-sdk tests cover origin-tag helpers, metadata constants, diagnostic and lifecycle models, representative parser fixtures, backward-compatible parsing, and optional-dependency isolation for protocol-specific adapters.
- Linden's real MCP integration tests verify unchanged `tools/list` output and normal tool results, plus rejection of unnamespaced metadata, malformed events, multiple origin tags, unsafe diagnostic shapes, and oversized payloads. No generic provider-conformance framework is required for this rollout.
- conversa tests verify that, when opted in, Modela event chunks are forwarded in order and interleaved with text; that nothing is forwarded or requested when not opted in; that `tool_executions` is never requested; and that non-streaming and error responses carry events.
- Portal and mobile tests verify account-scoped person/reminder invalidation, immediate handling of events interleaved with text, deduplication by `(source, id)` across Chat Completions and NATS delivery, rejection of events missing the related account, and preservation of applied invalidations when the chat later fails.
- An end-to-end tracer test covers create-person-with-birthday from conversa through Modela and Linden MCP, asserting that the full person remains the MCP/LLM result while the application receives `person.created` and `reminder.created` events and invalidates both listings. Publishing those same events through NATS preserves their identity and does not cause a second client reaction.
- Security tests use distinctive sensitive fixtures in normal tool results and prove they do not appear in exposed event data, diagnostic traces, validation logs, or telemetry.
- Failure tests verify that malformed `_meta` never changes the value returned to the model and never turns a successful tool result into an inference failure.
- Boundary tests verify call count, event count, serialized extension size, depth, item-count, and one-marker truncation behavior without retaining suppressed records.
- Disconnect tests verify client-side reconciliation of open calls and treat server-generated aborted records as best-effort.
- Performance tests benchmark metadata validation and serialization separately from MCP execution. The opted-out path must not parse or retain metadata beyond what is required to return the normal result.
- Performance tests establish a pre-change baseline and report p50 and p95 overhead for the opted-out path and for representative one-event and multi-event responses. A regression beyond the agreed repository-specific budget blocks rollout until explained and approved; correctness is not traded for speculative micro-optimization.
- Existing MCP tool tests, Modela MCP executor/toolset tests, completion streaming tests, and agent-runner event tests provide prior art for the new coverage.

## Definition of Done

- All functional, security, authorization, compatibility, failure, and performance acceptance criteria in this PRD pass in every affected repository.
- The same Tessera `Event` instance or immutable serialized value is used by the MCP and NATS delivery adapters for a domain occurrence, with identity-preservation tests proving the invariant.
- The touched paths have one clear owner for event construction, disclosure policy, metadata validation, and client reconciliation; no duplicated generic event model remains.
- Necessary adjacent refactors are complete, obsolete code is deleted, and any non-blocking deferred cleanup has a linked issue with scope, rationale, owner, and removal condition.
- Public interfaces and event-data schemas are documented, versioned where appropriate, and represented by typed models rather than informal dictionaries.
- Every reusable Python contract, constant, validator, parser, serializer, and representative parser fixture is owned by tessera-sdk; consuming backend repositories import it directly, and superseded local definitions are deleted.
- Linden's migrated MCP tools pass provider-owned integration tests proving that normal tool behavior is preserved and emitted metadata satisfies the shared SDK contracts.
- Pull requests include a concise architecture note describing module seams, invariants, performance impact, migration behavior, and why any new abstraction earns its interface.
- Operational rollout and rollback steps are documented. Disabling event exposure must not disable normal MCP execution or change the complete result returned to the LLM and direct MCP callers.

## Out of Scope

- Reducing, filtering, or replacing the normal MCP result returned to authorized direct MCP clients.
- Making MCP a less capable interface than the corresponding authorized HTTP API.
- Automatically deriving domain events by diffing tool arguments, results, database rows, or assistant text.
- Automatically exposing complete tool arguments or results for diagnostics.
- Frontend-specific cache keys, page refresh commands, navigation commands, or state-management instructions.
- Persisting Chat Completions event delivery or diagnostic traces for replay, audit, session history, or analytics. Existing NATS publication is not persistence introduced by this PRD.
- Cross-request event delivery, webhooks, push notifications, or a general event bus.
- Direct web or mobile connectivity to the internal NATS cluster, or implementation of an authenticated WebSocket/SSE gateway backed by NATS.
- Designing or implementing Modela's plugin lifecycle, packaging, discovery, installation, permissions, isolation model, or provider certification. Those decisions belong to the plugin PRD when concrete plugin work begins.
- Guaranteeing event delivery after an SSE disconnect.
- Defining operation IDs, queued-work events, status endpoints, progress events, completion protocols, or any other lifecycle contract for asynchronous or long-running tools.
- Migrating every controlled MCP tool in one release.
- Changing MCP authentication, tool authorization, retries, timeouts, or agent maximum-round behavior. Transaction-boundary fixes required to make the migrated person commands atomic are explicitly in scope; unrelated command paths are not.
- Supporting arbitrary or unnamespaced MCP metadata. Only recognized metadata keys whose values pass SDK-owned validation, version, and size rules are eligible for exposure.
- Project-scoped diagnostic permissions. These require ModelConfig to carry a project, which is separate work.
- Forwarding diagnostic traces through conversa or to end-user applications.
- Publishing cross-language schemas, generated clients, or another shared runtime contract package. Controlled backend services reuse tessera-sdk Python models; React-facing types belong at the application API boundary that consumes the completion response.

## Further Notes

- “Normal result” is deliberately used instead of “private result” or “model result.” The complete tool result belongs to every authorized MCP caller, not only the LLM.
- MCP `_meta` is additive metadata, not a confidentiality mechanism. Direct MCP clients may receive it, so every value placed there must itself be safe for the authenticated MCP caller.
- Chat Completions clients receive metadata only through the requested and authorized extension channels. Modela does not expose normal MCP results merely because it is acting as the MCP client.
- Domain events state facts about completed domain operations. Applications remain responsible for deciding whether to refetch, patch a cache, display a toast, or navigate.
- PRD 0021 should be marked superseded if this PRD is approved for implementation, because its Modela-side field-selection policy conflicts with the tool-authored metadata approach defined here.
- The existing follow-up issue for persistence remains applicable to diagnostic traces and Chat Completions delivery history. Durable NATS retention/replay and historical application-event delivery require a separate product decision because response-time cache invalidation and event replay solve different problems.
