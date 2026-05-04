# PRD 0011 — ModelConfig MCP Association & Completion Tool Loop

## Problem Statement

Modela's MCP infrastructure (server registry, tool catalog, tool executor, credential management) is fully operational after PRD 0008. However, the completion command does not yet invoke the agentic tool loop. Operators cannot declare which MCP servers are available for a given ModelConfig, and no `MCPToolset` adapter bridges the existing tool catalog to pydantic-ai's `Agent`. As a result, every completion request is a single-turn LLM call with no tool access, regardless of what MCP servers are registered.

## Solution

Introduce a many-to-many association between `ModelConfig` and `MCPServer`. Each ModelConfig declares its own set of permitted MCP servers. When a completion request resolves a ModelConfig, the command loads tools only from the associated servers, constructs an `MCPToolset` adapter, and passes it to the pydantic-ai `Agent`, enabling the full agentic loop already designed in PRD 0008.

Operators manage the association through dedicated REST endpoints. The completion API is unchanged.

## User Stories

1. As an operator, I want to attach one or more MCP servers to a ModelConfig, so that completions using that config have access to the right set of tools.
2. As an operator, I want to detach an MCP server from a ModelConfig, so that I can revoke tool access without deleting the server registration.
3. As an operator, I want to list all MCP servers attached to a ModelConfig, so that I can audit which tools are available for a given model.
4. As an operator, I want to list all ModelConfigs that reference a given MCP server, so that I can assess the blast radius before disabling a server.
5. As an API consumer, I want tool-capable ModelConfigs to automatically run the agentic loop, so that I receive a final text answer without managing tool-call round-trips myself.
6. As an API consumer, I want the completion response shape to remain unchanged whether or not tools were used, so that I don't need to update client code when tools are added to a ModelConfig.
7. As an API consumer, I want tool execution errors to be surfaced to the LLM as structured results rather than HTTP errors, so that the model can reason about failures and recover.
8. As an operator, I want to cap the number of tool-call rounds on a ModelConfig, so that runaway agentic loops don't consume unbounded tokens (see also PRD 0008 `max_tool_rounds`).
9. As an operator, I want a ModelConfig with no attached MCP servers to behave exactly like the current single-turn completion path, so that existing integrations are unaffected.
10. As an operator, I want to disable an MCP server globally and have it excluded from all ModelConfig tool sets automatically, so that I don't need to remove the association from every ModelConfig manually.
11. As an operator, I want to create a ModelConfig without any MCP servers and attach them later, so that I can evolve tool access independently of model configuration.
12. As a developer, I want the MCPToolset adapter to be independently testable against a mock executor, so that tool-loop behaviour can be verified without a live MCP server.
13. As a developer, I want per-ModelConfig tool loading to be covered by integration tests, so that regressions in the association query are caught before they reach production.
14. As an operator, I want token usage logged per LLM round-trip across the full agentic loop, so that per-request cost attribution is accurate even for multi-round tool calls.

## Implementation Decisions

### Schema changes

**New join table: `model_config_mcp_servers`**

| Column            | Type                           | Notes        |
| ----------------- | ------------------------------ | ------------ |
| `model_config_id` | UUID (FK → `model_configs.id`) | Composite PK |
| `mcp_server_id`   | UUID (FK → `mcp_servers.id`)   | Composite PK |
| `created_at`      | TIMESTAMPTZ                    | Auto-set     |

No `deleted_at` column — rows are hard-deleted. If a server is globally disabled, it is excluded at query time via `mcp_servers.enabled = true`, not by removing join rows.

No additional columns on `model_configs` or `mcp_servers` beyond what PRD 0008 already specifies.

### ModelConfig → MCPServer relationship

The SQLAlchemy `ModelConfig` model gains a many-to-many `relationship` to `MCPServer` via the join table. The relationship is loaded explicitly (not eagerly) in the repository to avoid N+1 queries.

### MCPToolCatalogRepository

A new method `get_tools_for_model_config(model_config_id)` replaces the existing `get_tools_for_request()` when called from the completion command. It:

1. Joins `model_config_mcp_servers` to `mcp_servers` on `mcp_server_id = id` where `enabled = true` and `deleted_at IS NULL`.
2. For each resulting server, resolves auth headers via `CredentialApplier` and fetches tools via `ToolCatalog`.
3. Returns the aggregated `MCPCatalogTool` list. Per-server failures are logged and skipped; the remaining tools are returned.

`get_tools_for_request()` is retained for any future per-request filtering use case from PRD 0008.

### MCPToolset adapter

**Already implemented.** `MCPToolset` (in the MCP services layer) implements pydantic-ai's `AbstractToolset[None]`:

- `get_tools(ctx)` converts each `MCPCatalogTool` to a pydantic-ai `ToolsetTool` with a `ToolDefinition` derived from the catalog tool's `qualified_name`, `description`, and `input_schema`.
- `call_tool(name, tool_args, ctx, tool)` looks up the catalog tool by qualified name, delegates to `MCPToolExecutor.execute()`, and returns a JSON string result.
- Accepts an optional `user_id` for delegated credential resolution, forwarded to `MCPToolExecutor`.

The adapter holds only a list of `MCPCatalogTool` and an `MCPToolExecutor` reference — no DB session, no repository. No changes needed to this component.

### Completion command changes

`CreateCompletionCommand.execute()` is updated:

1. After resolving the `ModelConfig`, call `MCPToolCatalogRepository.get_tools_for_model_config(config.id)`.
2. If the tool list is non-empty, construct `MCPToolset(tools, executor)` and pass `toolsets=[toolset]` to `agent.run()`.
3. If the tool list is empty, pass `toolsets=[]` — identical to the current code path.
4. Pass `max_result_retries=config.max_tool_rounds` (or the default from PRD 0008) to `agent.run()`.

The completion response shape is unchanged.

### Association CRUD API

New endpoints under the existing `model_configs` resource:

| Method   | Path                                            | Description                           |
| -------- | ----------------------------------------------- | ------------------------------------- |
| `POST`   | `/model-configs/{uuid}/mcp-servers`             | Attach an MCP server to a ModelConfig |
| `DELETE` | `/model-configs/{uuid}/mcp-servers/{server_id}` | Detach an MCP server                  |
| `GET`    | `/model-configs/{uuid}/mcp-servers`             | List attached MCP servers (paginated) |

Request body for `POST`:

```json
{ "server_ids": ["server_uuid_id"] }
```

Response for list: same shape as `GET /mcp-servers` items (server metadata, no credential values).

Attaching an already-attached server returns `200` (idempotent). Attaching a non-existent or soft-deleted server returns `404`. Attaching a disabled server is allowed (it will be excluded from tool loading at runtime but the association is preserved).

RBAC: same permissions as ModelConfig management (`modela.model_config:write`). Reading the association list requires `modela.model_config:read`.

### Tool executor instantiation

`MCPToolExecutor` is instantiated once per request in `CreateCompletionCommand` and passed to `MCPToolset`. It holds a DB session reference for server lookups. No singleton or module-level state.

### Error handling

Tool execution errors (timeout, MCP error) return a structured JSON string to the LLM, not an HTTP exception — per the existing `MCPToolExecutor` contract from PRD 0008. No changes to error handling behaviour.

If the entire tool catalog load fails (e.g., all MCP servers unreachable), the completion proceeds with no tools rather than failing. This is consistent with the per-server graceful-skip policy already in `MCPToolCatalogRepository`.

## Testing Decisions

**What makes a good test:** tests exercise observable external behaviour — HTTP responses, DB state, return values — not internal method calls or implementation details. Tests must not depend on a live MCP server; use `fastmcp`'s in-process test transport or mock `MCPToolExecutor` directly.

**Prior art:** existing router tests in `tests/routers/` use `create_client_fixture`, function-scoped DB sessions with rollback, and dependency overrides for auth. Integration tests for commands create real DB rows and assert on return values or DB state. Follow these patterns.

### Modules with test coverage

**MCPToolset adapter**

- `get_tools` converts a list of `MCPCatalogTool` to the correct pydantic-ai `ToolsetTool` format (qualified name, description, JSON schema preserved).
- `call_tool` with a valid qualified name delegates to `MCPToolExecutor.execute()` and returns the result.
- `call_tool` with an unknown qualified name raises the appropriate error.

**MCPToolCatalogRepository — `get_tools_for_model_config`**

- Returns tools only from servers attached to the specified ModelConfig.
- Excludes tools from servers that are disabled (`enabled=False`), even if attached.
- Excludes tools from servers that are soft-deleted.
- A server that raises during tool fetch is skipped; remaining servers' tools are still returned.
- A ModelConfig with no attached servers returns an empty list.

**Completion command — tool wiring**

- A completion request against a ModelConfig with attached, enabled MCP servers results in `agent.run()` receiving a non-empty `toolsets` list.
- A completion request against a ModelConfig with no attached servers results in `agent.run()` receiving `toolsets=[]`.
- A completion request against a ModelConfig with only disabled attached servers results in `toolsets=[]`.

**Association router**

- `POST /model-configs/{uuid}/mcp-servers` with a valid `server_id` creates the join row and returns `200`.
- `POST /model-configs/{uuid}/mcp-servers` with an already-attached `server_id` is idempotent and returns `200`.
- `POST /model-configs/{uuid}/mcp-servers` with a non-existent `server_id` returns `404`.
- `DELETE /model-configs/{uuid}/mcp-servers/{server_id}` removes the join row and returns `204`.
- `DELETE /model-configs/{uuid}/mcp-servers/{server_id}` for a non-attached server returns `404`.
- `GET /model-configs/{uuid}/mcp-servers` returns paginated attached servers; soft-deleted servers are excluded.
- All endpoints return `403` without the required RBAC permission.

## Out of Scope

- Per-request tool filtering (the `tools.servers` / `tools.tool_names` request field from PRD 0008) — not removed, not modified.
- Streaming + agentic loop — deferred per PRD 0008 amendment.
- Per-tool allow/deny lists on the association (e.g., "attach GitHub server but only the `create_issue` tool") — a future refinement.
- Reordering or prioritising attached MCP servers — first-loaded-wins is sufficient for this phase.
- UI or admin dashboard for managing associations — REST API only.
- Bulk attach/detach (attach multiple servers in one request) — add per server for now.

## Further Notes

`MCPToolset` is already implemented (one import path correction applied during review). The remaining new components are the join table, the association query in `MCPToolCatalogRepository`, the CRUD endpoints, and the wiring in `CreateCompletionCommand`. Everything else (executor, catalog, credential resolution) already exists. The primary risk is latency: cold tool catalog fetches happen synchronously in the completion request path. The per-server `tool_cache_ttl_seconds` (default 300 s) mitigates steady-state cost, but operators should be aware that the first request to a ModelConfig after a cache miss will pay the latency of fetching tool lists from all attached servers before the first LLM call.

The association join table uses hard deletes. If a ModelConfig is soft-deleted, its join rows become orphaned but harmless (the server is looked up by `model_config_id` which will never match an active request). A follow-up migration can clean these up if needed.
