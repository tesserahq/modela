## Problem Statement

Modela executes built-in and MCP tools inside its agentic completion loop, but callers of `POST /chat/completions` can observe only assistant text. The portal therefore cannot show users which tools a model selected, which approved and redacted inputs were supplied to those tools, whether execution succeeded, or which approved and redacted result fields informed the final answer.

Exposing these internal calls as ordinary Chat Completions `tool_calls` would be misleading. In the standard Chat Completions contract, a tool call transfers execution responsibility to the client and ends that completion turn with `finish_reason: "tool_calls"`. Modela must remain the executor because it owns MCP connectivity, credentials, retries, built-in tools, and the multi-round agent loop. The endpoint needs an additive observability extension that preserves existing behavior for standard clients while making internally executed tools visible to opted-in callers.

Tool arguments and results may contain secrets, personal data, or very large payloads. A generic sanitizer cannot prove arbitrary tool output safe: sensitive data may appear as free text or under an innocuous field name. Observability must therefore be explicitly requested and authorized, metadata-first, limited to fields a ModelConfig owner has explicitly approved for exposure, redacted immediately before serialization as defense in depth, strictly bounded, and fast enough that it does not materially delay model responses.

## Solution

Add opt-in tool-execution observability to both streaming and non-streaming Chat Completions responses. A caller requests it with `include: ["tool_executions"]`, must hold a dedicated inspection permission, and the resolved ModelConfig must explicitly allow it. Calls that do not opt in retain the existing response behavior and payload size.

Streaming responses continue to use valid `chat.completion.chunk` envelopes. Tool activity is represented by an additive `extensions.tool_execution` object. During a healthy connection, each invocation emits a `started` event followed by one `completed` event, correlated by `call_id`. Delivery is best-effort when the run or transport terminates abnormally: the server emits `aborted` completions when it detects failure while the stream remains writable, and the client reconciles any still-open calls when the stream ends. Text chunks remain unchanged and may be interleaved with tool events in actual execution order.

Non-streaming responses include a consolidated, ordered trace under `extensions.tool_executions`, with one record per invocation. The trace is response-only and is not persisted by this feature.

Execution metadata is available for approved, opted-in requests. Arguments, results, and errors are omitted by default. A ModelConfig owner may explicitly allow selected fields for individual qualified tools using JSON Pointer allowlists. Allowed values are then processed by one bounded, single-pass redactor immediately before exposure. Redaction is performed only for opted-in requests and never modifies the values used by the agent. If selection or redaction fails, the affected data is omitted; raw data is never used as a fallback, and inference continues normally.

## User Stories

1. As a portal user, I want to see when the model starts a tool, so that I understand what it is doing while I wait.
2. As a portal user, I want to see when a tool finishes, so that I can distinguish active work from a stalled response.
3. As a portal user, I want to see approved and redacted tool arguments, so that I understand why the tool was invoked without receiving fields the config owner did not approve.
4. As a portal user, I want to see an approved and redacted tool result, so that I understand what evidence informed the final answer without receiving arbitrary tool data.
5. As a portal user, I want failed and aborted tool calls to be identified clearly, so that I can understand incomplete or degraded answers.
6. As a portal developer, I want stable call IDs, so that I can correlate start and completion events even when tools run in parallel.
7. As a portal developer, I want ordered sequence numbers, so that I can render a deterministic activity timeline.
8. As a portal developer, I want duration data for completed calls, so that I can communicate execution latency to users.
9. As a portal developer, I want the same semantic fields for built-in and MCP tools, so that the UI does not depend on backend transport details.
10. As a portal developer, I want streaming events to arrive as tool execution progresses, so that the interface can update in real time.
11. As an API consumer, I want a consolidated non-streaming trace, so that I can inspect executions without parsing SSE.
12. As an existing OpenAI-compatible client, I want unchanged behavior unless I opt in, so that this feature does not break my integration.
13. As an API consumer, I want unsupported `include` values rejected, so that configuration mistakes fail visibly.
14. As a security owner, I want common secret-bearing fields redacted recursively, so that credentials are not returned through observability data.
15. As a security owner, I want credentials and sensitive query parameters removed from URLs, so that secrets embedded in addresses are not exposed.
16. As a security owner, I want exposure-filter failures to omit data rather than expose raw values, so that observability fails closed.
17. As a platform operator, I want payload depth, item count, and byte size bounded, so that hostile or accidental tool output cannot consume unbounded resources.
18. As a platform operator, I want execution observability to preserve existing agent behavior, so that enabling it cannot change model decisions or tool outcomes.
19. As a model developer, I want recoverable tool errors to remain available to the agent, so that it can adapt or choose another approach.
20. As a model developer, I want unexpected infrastructure failures to retain existing endpoint semantics, so that observability does not hide operational faults.
21. As a performance owner, I want selection and redaction to target less than one millisecond p95 for ordinary events, so that observability does not materially delay responses.
22. As a performance owner, I want the exposure filter skipped entirely when execution traces are not requested, so that existing callers pay no processing cost.
23. As a maintainer, I want the public extension namespace to be independent of the product or service name, so that rebranding does not require a protocol change.
24. As a maintainer, I want transport-specific MCP details excluded, so that the public contract remains stable if internal execution changes.
25. As a maintainer, I want execution traces to be ephemeral in this phase, so that retention and historical access can be designed separately.
26. As a ModelConfig owner, I want to decide whether callers may see tool executions for my config, so that tool output fetched with shared credentials or guarded by my system prompt is not exposed without my consent.
27. As a platform operator, I want the total trace size per response bounded, so that long or highly parallel tool loops cannot produce unbounded responses.
28. As a security owner, I want inspecting tool executions to require a permission distinct from creating completions, so that ordinary chat access does not imply access to internal data sources.
29. As a ModelConfig owner, I want execution details to default to metadata-only and to allowlist exposed fields per tool, so that enabling observability does not expose arbitrary payloads.
30. As a portal developer, I want an explicit trace-truncation signal, so that the UI can explain when later tool events were deliberately omitted.
31. As a portal developer, I want open calls reconciled when an SSE stream ends unexpectedly, so that the UI never displays a permanently running tool.

## Implementation Decisions

- Modela remains the tool executor. The portal observes execution but does not receive credentials, connect to MCP servers, implement retries, or drive the agent loop.
- The request schema gains an optional top-level `include` collection. The only value introduced by this PRD is `tool_executions`; any unsupported value produces a `422` validation response identifying the unsupported values. OpenAI SDK users, whose `chat.completions.create()` has no `include` parameter, pass it as `extra_body={"include": ["tool_executions"]}`; the SDK merges `extra_body` into the top-level JSON body.
- `CompletionCreate`'s `extra_body` field is not dead: the tessera-sdk `ModelaClient` sends `extra_body` as a literal nested key, even though Modela does not currently read it. Modela therefore accepts `extra_body.include` as an alias for top-level `include` and merges the two. A `422` is returned only when both are present with different values, or when either contains an unsupported value. Rejecting the nested form would break every tessera-sdk caller (see PRD 0022).
- Exposure is gated per ModelConfig. ModelConfig gains `expose_tool_executions: bool` (default `false`, requires a migration), editable through the existing ModelConfig update endpoint and its `update` permission. If a request includes `tool_executions` and the resolved config has the flag off, the command returns `403` before inference starts.
- ModelConfig also gains a structured `tool_execution_exposure` policy. Its default exposes metadata only. The policy is keyed by qualified tool name and independently allowlists argument and result fields using RFC 6901 JSON Pointers. No wildcard or whole-object exposure is allowed in the initial implementation. Error category remains metadata; error detail follows the result allowlist. Policies referencing tools not available to the config or invalid pointers are rejected on create/update. A missing tool policy exposes no arguments, result, or error detail.
- `POST /chat/completions` gains the `create` RBAC dependency (`Depends(_rbac["create"])`), matching `summarize_router`. The router already builds `_rbac` but never applies it, so today the endpoint authenticates callers without authorizing them.
- A caller requesting `tool_executions` must additionally hold a dedicated `completion.inspect_tool_executions` permission for the resolved project. Authorization is enforced before tool catalog loading or inference begins. The ModelConfig flag expresses owner consent; the inspection permission expresses caller authorization. Neither substitutes for the other. Requests without `tool_executions` require only the existing completion `create` permission.
- Tool observability is disabled when `tool_executions` is absent. No trace is assembled, selected, or redacted for non-opted-in requests.
- Internally executed tools are not exposed through standard `delta.tool_calls`. That field communicates that the client must execute the call and could cause duplicate execution. The ordinary assistant response and final `finish_reason` retain their current semantics.
- Streaming execution events use the existing Chat Completions chunk envelope (`id`, `object: "chat.completion.chunk"`, `created`, `model`) with `choices: []` and an added `extensions.tool_execution`. This matches the shape OpenAI uses for its usage-only chunk, so OpenAI-compatible accumulators skip it without changing the assistant message. The `role: "assistant"` delta is attached to the first *text* chunk, never to a tool-event chunk; tool events do not count as the first delta.
- A streaming `started` event contains `sequence`, `event`, `call_id`, and `name`. It contains `arguments` only when the tool exposure policy selects at least one argument field and redaction succeeds.
- A streaming `completed` event contains `sequence`, `event`, `call_id`, `name`, `status`, and `duration_ms`. It contains `result` or error `detail` only when the tool exposure policy selects at least one corresponding field and redaction succeeds.
- Execution status is one of `success`, `error`, or `aborted`. There is no `denied` status: Modela has no tool-approval flow, and pydantic-ai produces `ToolDenied` only through deferred-tool approval. `denied` may be added if an approval flow is introduced.
- Status comes from the tool's actual outcome, not from the shape of the agent-visible return value. `MCPToolExecutor` currently returns every failure (timeout, transport exception, `is_error` result, unknown server) as an ordinary value, which pydantic-ai reports as a successful `ToolReturnPart`. Its internal return contract therefore changes to a typed `ToolExecutionResult` carrying `status`, `agent_value`, `observable_value`, and optional `error_category`. `MCPToolset.call_tool` records the typed outcome in a request-scoped observer keyed by `ctx.tool_call_id`, then returns `agent_value` unchanged to pydantic-ai. Successful tool data that happens to contain keys such as `error` is not misclassified. For built-in tools, a `RetryPromptPart` maps to `error`, a `ToolReturnPart` to `success`, and an unhandled exception leaves the call open for abnormal-run reconciliation.
- The public `error` never contains raw exception text. It is `{ "category": ..., "detail": ... }`, where `category` is one of `timeout`, `server_unavailable`, `tool_error`, `invalid_arguments`, or `not_found`. `detail` is present only for `tool_error`, where it contains approved and redacted fields from the MCP tool's own error payload. Transport exception messages (which, for httpx, include the full server URL) and internal identifiers such as `server_id` stay in internal logs only.
- If a run ends abnormally while calls are open (for example, a provider error or unexpected infrastructure exception), the server attempts to emit a `completed` event with `status: "aborted"` and no `result` or `error` for every recorded `call_id` that has a `started` but no `completed` event, then closes. This is best-effort and is possible only while the transport remains writable. On EOF, transport error, or disconnect, the portal marks every locally open call `aborted` or `unknown`; the wire contract does not promise exactly-once completion across a broken connection. A non-streaming request that fails returns its existing error response without a trace.
- Parallel calls are supported. Events are emitted in observed execution order and correlated exclusively through `call_id`; completion order is not required to match start order.
- Non-streaming responses add `extensions.tool_executions`, an ordered array containing one consolidated record per call. A request that opts in but executes no tools returns an empty array. Non-streaming runs collect events through pydantic-ai's `event_stream_handler` on `agent.run()` rather than switching to the streaming path.
- When a response does not opt in, `extensions` is omitted, not serialized as `null`. Because the route uses `response_model=CompletionResponse`, the route sets `response_model_exclude_unset=True` (or the command returns a distinct response model only when tracing is on), so the default payload is byte-for-byte unchanged.
- The public representation is uniform for built-in and MCP tools. It exposes the qualified tool name but excludes server URLs, authentication information, internal toolset identifiers, and transport details.
- Tool events are observational. Enabling them cannot alter arguments, results, retries, model context, error recovery, or the ultimate completion outcome.
- Recoverable execution failures continue to be returned to the agent according to existing behavior and are exposed with `status: "error"`. Unexpected infrastructure exceptions retain existing endpoint failure behavior, apart from the `aborted` events described above.
- A dedicated exposure filter encapsulates JSON Pointer selection, recursive redaction, URL cleaning, traversal limits, byte budgeting, and truncation behind one small interface that accepts a value, an allowlist, and a size budget and returns an approved representation plus redaction metadata.
- Allowlist selection is the primary disclosure boundary. The redactor is defense in depth and does not claim to discover every possible secret or item of personal data. It redacts values associated with case-insensitive sensitive keys and close normalized variants, including authorization, token, API key, password, secret, and cookie fields.
- URL user information and sensitive query parameters are removed before exposure.
- Redacted values use the literal string `[REDACTED]`.
- Arguments have a maximum emitted size of 16 KiB. Results and errors have a maximum emitted size of 64 KiB.
- Sanitization traverses at most 20 levels and 1,000 container items per value. Oversized or over-budget branches are truncated without fully copying or scanning them.
- Each response has a 1 MiB total serialized extension budget and a maximum of 100 recorded calls (200 lifecycle events), both configuration-backed server defaults. The budget includes event metadata, selected payloads, and serialization overhead rather than payload values alone. When either limit is reached, the observer stops retaining new calls and payloads, emits at most one `extensions.tool_execution` event with `event: "trace_truncated"`, and suppresses subsequent execution events. Non-streaming responses append one equivalent truncation record. This bounds both wire size and observer memory even though the number of executed calls is currently unbounded. In particular, `config.max_tool_rounds` is passed to pydantic-ai as `output_retries`, which does not limit tool rounds, and the streaming path does not pass it at all. Fixing execution limits is outside this PRD and is tracked separately.
- Limits are configuration-backed server defaults and cannot be increased by callers.
- Truncation and redaction metadata is emitted only when applicable. Truncated data is explicitly marked with `truncated: true`.
- Selection and redaction occur immediately before response serialization and operate on an observable copy. Structured values are selected by JSON Pointer before unrelated branches are copied or scanned. For MCP tools, the source is `observable_value` from the typed executor result, not the JSON string returned to the agent. A selected string value that is itself JSON and starts with `{` or `[` within the byte budget gets exactly one bounded parse so its selected descendants can be resolved and redacted. If parsing, selection, or bounded inspection fails, the selected value is omitted with `redaction_status: "failed"`. An opaque string is emitted only when its exact JSON Pointer was explicitly allowlisted; it is still checked against known secret patterns, but the API does not describe that check as complete sanitization. Structured values are never serialized and re-parsed.
- Sanitizer failures never expose the original value. The event remains available with the affected arguments, result, or error omitted and `redaction_status: "failed"`; the failure is logged internally and inference continues.
- Wall-clock timestamps are omitted. Sequence numbers express ordering and `duration_ms` expresses elapsed execution time without adding non-deterministic or unnecessary data.
- Tool traces are not persisted in completion records, session history, or audit storage under this PRD.
- The implementation should separate agent event observation from API serialization. The observer should translate runtime-specific tool events into a small internal lifecycle representation; response assembly should translate that representation into streaming or consolidated public forms.
- The exposure filter should be a deep module independently testable from the agent runner and HTTP layer. Runtime event translation and the typed MCP result contract should likewise be testable without live providers or MCP servers.

## Testing Decisions

- Tests assert externally visible behavior and stable contracts rather than private helper call sequences.
- Request validation tests cover accepted opt-in requests, omitted `include`, empty `include`, duplicate values if allowed by the validation framework, unsupported values returning `422` with useful detail, `extra_body.include` accepted as an alias, and conflicting top-level and nested values returning `422`.
- Authorization tests verify `403` when `include` requests traces on a config with `expose_tool_executions: false`, `403` when the caller lacks `completion.inspect_tool_executions`, success only when both checks pass, project scoping of the inspection permission, and that ordinary completion requests still require only the `create` permission.
- Streaming router tests verify valid completion-chunk envelopes (tool-event chunks have `choices: []`), `role` on the first text chunk even when a tool event comes first, start/completion ordering, call-ID correlation, interleaving with text, parallel completion order, errors, and the final stop chunk.
- Abort tests verify that a provider error or unexpected exception during an open tool call emits `completed` with `status: "aborted"` when the stream remains writable. Portal contract tests verify that EOF or disconnect reconciles locally open calls without requiring a final server event.
- Non-streaming router tests verify consolidated ordered traces, an empty trace when no tools execute, and that the `extensions` key is absent (not `null`) for requests that do not opt in.
- Agent-runner tests verify uniform translation of built-in and MCP tool lifecycle events and confirm that observation does not change execution or model output.
- Status tests verify that each MCP failure path in `MCPToolExecutor` (timeout, transport exception, `is_error`, unknown server) yields a typed `ToolExecutionResult` with `status: "error"` and the right category, while `agent_value` remains unchanged. A successful payload containing `error` and `reason` keys remains successful.
- Leak tests verify that an httpx exception whose message contains a server URL, and the `server_id` from a not-found error, never appear in any emitted event.
- Exposure-filter tests cover valid and invalid JSON Pointers, absent paths, metadata-only defaults, per-tool isolation, nested mappings and collections, case and separator variants of sensitive keys, credential-bearing URLs, sensitive query parameters, non-JSON-native values, Unicode byte accounting, redaction metadata, and failure behavior.
- Exposure-filter tests also cover JSON-encoded selected strings: explicitly selected JSON containing `access_token` is redacted, invalid or oversized JSON is omitted when bounded inspection cannot complete, and an unselected or unparseable value is never emitted accidentally.
- Boundary tests verify the 16 KiB argument budget, 64 KiB result/error budget, 1 MiB total serialized-extension budget, 100-call limit, one truncation marker, depth 20, and 1,000-item traversal cap without depending on exact internal traversal mechanics. Non-streaming tests verify that observer memory stops growing after the call limit.
- Security tests verify that unallowlisted fields never appear, that metadata-only is the default, and that raw values never appear when selection or redaction fails.
- Regression tests verify that ordinary streaming and non-streaming responses are byte-for-byte unchanged when `tool_executions` is not requested.
- A dedicated benchmark records exposure-filter p50 and p95 for representative small, nested, sensitive, and near-limit payloads. The performance target is less than one millisecond p95 for ordinary events in a controlled environment.
- Ordinary CI does not use a strict wall-clock threshold because shared-runner noise would make it flaky. CI instead enforces hard structural bounds and runs functional regression tests; the benchmark is available for controlled performance verification.
- Existing completion streaming, agent runner, and toolset tests provide prior art for mocked agent events, tool-loop completion, and HTTP response assertions.

## Out of Scope

- Persisting tool execution traces for session history, audit, replay, or analytics.
- Retention policies, deletion policies, encryption-at-rest changes, or historical trace access control.
- Portal UI implementation.
- Moving tool execution responsibility from Modela to callers.
- Accepting caller-defined tool schemas or caller-executed tool results through this feature.
- Exposing MCP credentials, server addresses, internal toolset identifiers, provider-private metadata, unapproved fields, or raw unredacted values.
- Per-tool custom redaction algorithms. The initial implementation supports per-tool field allowlists with one central defense-in-depth redactor.
- Streaming partial tool argument deltas. Only complete, execution-ready arguments are exposed.
- Adding wall-clock timestamps to execution events.
- Changing agent retry, timeout, parallelism, maximum-round, or error-recovery behavior. This includes fixing `max_tool_rounds` so that it actually limits tool rounds; that is tracked as a separate issue.
- Tool-approval flows and a `denied` execution status.
- Creating a separate Responses API or adopting its typed event protocol.

## Further Notes

- The additive extension is intentionally service-name-independent: `extensions.tool_execution` for a streamed lifecycle event and `extensions.tool_executions` for a completed non-streaming trace.
- The extension preserves the outer Chat Completions response shape, but it is not part of the OpenAI Chat Completions standard. Consumers must explicitly request and understand it.
- The portal should render approved and redacted values as explanatory observability data, not as proof that a side effect succeeded independently of the reported execution status.
- A follow-up GitHub issue tracks secure persistence and historical replay. That work must revisit authorization, retention, deletion, storage growth, and whether data is stored before or after sanitization.
