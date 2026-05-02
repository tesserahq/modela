# PRD 0008 — MCP Registry & Tool Orchestration

## Overview

This phase introduces pydantic-ai as Modela's internal agentic loop orchestrator, an MCP server registry, and the full tool execution infrastructure. When a completion request involves tools, Modela runs the agentic loop internally — calling MCP tools, re-prompting the model with results, and returning the final response. Every LLM call in the loop routes through Modela's existing ModelConfig / provider / logging stack. The consumer API is unchanged.

---

## Goals

- Extend `ModelaModel` (introduced in PRD 0001) with MCP tool support via pydantic-ai's `AbstractToolset`
- Introduce `MCPServer` registry: named, URL-based MCP server configuration with optional credentials
- Implement tool catalog: discover + cache tools from all enabled MCP servers
- Implement tool executor: call MCP servers with timeout, return structured errors to LLM on failure
- Add `max_tool_rounds` to ModelConfig to cap agentic loops
- Allow callers to filter available tools per request (by server slug and/or individual tool name)
- Log aggregate token usage across all rounds of an agentic request

---

## Non-Goals

- Streaming + agentic loop (deferred — see PRD 0004 amendment note below)
- In-process or embedded MCP servers (all MCP servers are remote HTTP/SSE)
- Custom tool definitions supplied per request (tools come from the MCP registry only)
- Per-ModelConfig tool allow/deny lists (filtering is request-time only in this phase)

---

## Background

Conversa (the Tessera chat service) has a working implementation of MCP server registration, tool caching, and agentic execution via pydantic-ai. The patterns are proven in production. This PRD ports them to Modela. `ModelaModel` (established in PRD 0001) already intercepts every LLM call for gateway concerns. This PRD adds `MCPToolset` instances to the `Agent` call, enabling the agentic loop without changing `ModelaModel` itself.

---

## ModelConfig Changes

New field on `model_configs`:

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `max_tool_rounds` | INTEGER | `10` | Maximum tool-call rounds in a single agentic request. `null` uses the system default (10). |

When the cap is reached, pydantic-ai stops the loop and the response is returned with `finish_reason: "max_rounds"`.

---

## MCP Server Registry

### DB Schema

**Table: `mcp_servers`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `server_id` | VARCHAR(100) | Unique slug used in tool names and request filters (e.g. `github`, `postgres-prod`) |
| `name` | VARCHAR(255) | Human-readable label |
| `url` | TEXT | MCP server base URL (HTTP/SSE transport) |
| `enabled` | BOOLEAN | Default `true`. Disabled servers are excluded from tool catalog. |
| `credential_id` | UUID (FK) | Optional. References `mcp_credentials.id`. |
| `tool_prefix` | VARCHAR(50) | Prefix for qualified tool names. Defaults to `server_id`. |
| `tool_cache_ttl_seconds` | INTEGER | Tool catalog cache TTL. Default: `300`. |
| `created_at` | TIMESTAMPTZ | Auto-set |
| `updated_at` | TIMESTAMPTZ | Auto-updated |
| `deleted_at` | TIMESTAMPTZ | Soft delete |

**Constraints:** `server_id` unique among non-deleted rows.

### CRUD API

All endpoints require admin-level RBAC (`modela.mcp_server:*`).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mcp-servers` | Register an MCP server |
| `GET` | `/mcp-servers` | List all servers (paginated) |
| `GET` | `/mcp-servers/{server_id}` | Get by server_id |
| `PUT` | `/mcp-servers/{server_id}` | Update fields |
| `POST` | `/mcp-servers/{server_id}/refresh-tools` | Force-refresh tool catalog (async Celery task) |
| `DELETE` | `/mcp-servers/{server_id}` | Soft delete |

**Request body (create/update):**

```json
{
  "server_id": "github",
  "name": "GitHub MCP Server",
  "url": "https://mcp.github.com/sse",
  "enabled": true,
  "credential_id": "uuid-of-credential",
  "tool_prefix": "github",
  "tool_cache_ttl_seconds": 300
}
```

---

## MCP Credentials

A general-purpose credential model for authenticating to MCP servers. This is distinct from BYOK provider keys (PRD 0006), which cover LLM provider API keys. MCP credentials cover HTTP-based authentication to tool servers.

### DB Schema

**Table: `mcp_credentials`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `name` | VARCHAR(255) | Human-readable label |
| `type` | VARCHAR(50) | `bearer_auth`, `basic_auth`, `api_key` |
| `encrypted_data` | BYTEA | Fernet-encrypted JSON blob containing the credential fields |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `deleted_at` | TIMESTAMPTZ | Soft delete |

Credential values are encrypted using Fernet (`app/security/crypto.py`, already present). The raw value is never returned in API responses after creation.

**Credential type payloads (before encryption):**

```json
// bearer_auth
{ "token": "..." }

// basic_auth
{ "username": "...", "password": "..." }

// api_key
{ "header": "X-Api-Key", "value": "..." }
```

### CRUD API

All endpoints require admin-level RBAC (`modela.mcp_credential:*`).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mcp-credentials` | Create a credential |
| `GET` | `/mcp-credentials` | List credentials (name and type only — no values) |
| `GET` | `/mcp-credentials/{id}` | Get credential metadata |
| `PUT` | `/mcp-credentials/{id}` | Update (re-encrypts on write) |
| `DELETE` | `/mcp-credentials/{id}` | Soft delete |

---

## Tool Catalog

`ToolCatalog` discovers tools from all enabled MCP servers and caches results per server.

- **Cache key:** `modela:mcp:tools:{server_id}`
- **Cache TTL:** from `mcp_servers.tool_cache_ttl_seconds`
- **Cache backend:** Redis (already present)
- **On cache miss:** connects to MCP server via `fastmcp.Client` with `StreamableHttpTransport`, fetches the tool list, serialises as JSON, writes to cache
- **Cache invalidation:** on server config change or explicit `/refresh-tools` call

**`MCPCatalogTool` internal type:**

```python
@dataclass
class MCPCatalogTool:
    qualified_name: str   # e.g. "github__create_issue"
    original_name: str    # e.g. "create_issue"
    description: str
    input_schema: dict    # JSON Schema
    server_id: str
```

Qualified name format: `{tool_prefix}__{original_name}` (double underscore separator).

**`MCPToolCatalogRepository.get_tools_for_request(filter)`** aggregates tools across all enabled servers, applies the request-time filter, and gracefully skips any server that fails to load (logs a warning, continues with remaining servers).

---

## Tool Execution

`MCPToolExecutor.execute(server_id, original_name, args)` handles a single tool call:

1. Look up server in registry
2. Resolve auth headers from associated credential (if any)
3. Connect to server via `fastmcp.Client`, call the tool with a 20-second timeout
4. On success: return tool output as a JSON string
5. On timeout: return `{"error": "ToolTimeout", "reason": "Tool execution exceeded 20s"}`
6. On MCP error: return `{"error": "ToolError", "reason": "<provider message>"}`

Errors are returned as structured dicts, **not exceptions**. pydantic-ai passes the error string back to the LLM as a tool result, allowing the model to reason about the failure and try an alternative approach.

---

## MCPToolset Adapter

`MCPToolset` bridges the tool catalog and executor to pydantic-ai's `AbstractToolset` interface:

```python
class MCPToolset(AbstractToolset[None]):
    def get_tools(self, ctx) -> list[ToolsetTool]:
        # Convert MCPCatalogTool[] → pydantic-ai ToolsetTool[] with ToolDefinition
        ...

    async def call_tool(self, name, tool_args, ctx, tool) -> str:
        # Resolve server_id + original_name from qualified_name
        # Delegate to MCPToolExecutor.execute()
        ...
```

---

## Request Changes

`POST /chat/completions` gains an optional `tools` field for per-request tool filtering:

```json
{
  "model": "openai-gpt-4o",
  "messages": [{ "role": "user", "content": "Create a GitHub issue for the login bug." }],
  "tools": {
    "servers": ["github"],
    "tool_names": ["slack__post_message"]
  }
}
```

| Field | Type | Behaviour |
|-------|------|-----------|
| `tools` absent | — | All tools from all enabled MCP servers are available |
| `tools.servers` | `list[str]` | All tools from the named server IDs are included |
| `tools.tool_names` | `list[str]` | The named qualified tool names are included |
| Both fields | — | Union of matched tools |
| `tools: {}` | — | No tools available; non-agentic path used |

---

## Completion Flow

`create_completion_command` is updated to use `ModelaModel` + `Agent` for all requests:

1. Resolve ModelConfig by slug (or default)
2. Resolve API key via BYOK logic (PRD 0006) — project key first, platform key fallback
3. Load tool catalog filtered by request `tools` field (empty list if `tools: {}` or MCP not yet configured)
4. Construct `ModelaModel(model_config, resolved_api_key, project_id, settings)`
5. Construct `MCPToolset(filtered_catalog)` if tools are available, else `toolsets=[]`
6. Call `agent.run(messages, toolsets=toolsets, max_result_retries=model_config.max_tool_rounds)`
7. pydantic-ai orchestrates the loop: parse `tool_calls` → `MCPToolset.call_tool()` → inject result → re-prompt → repeat until `stop` or `max_rounds`; each LLM hop calls `ModelaModel.request()`, which logs usage and applies ModelConfig params
8. Return final response in OpenAI-compatible shape

`agent.run()` with `toolsets=[]` is a single LLM call — the same behaviour as the non-agentic path, just without the old `BaseProviderAdapter` indirection.

---

## Usage Logging for Agentic Requests

`ModelaModel.request()` fires a Celery usage log task on every call (each round-trip to the LLM). For the final `completion_requests` row, `create_completion_command` writes aggregate values:

- `input_tokens` / `output_tokens`: sum across all rounds
- `tool_rounds`: number of tool-call rounds executed
- `finish_reason`: `"stop"` (normal) or `"max_rounds"` (cap hit)

New column on `completion_requests`:

| Column | Type | Notes |
|--------|------|-------|
| `tool_rounds` | INTEGER | Number of tool-call rounds. `null` for non-agentic requests. |

---

## Amendment to PRD 0004 (Streaming)

**Streaming + agentic loop interaction is deferred.** If `stream: true` is set on a request that would otherwise enter the agentic loop (tools available), Modela returns `422 IncompatibleOptions` in this phase. Full streaming of agentic loops — streaming token deltas mid-loop — requires coordinating SSE with multi-round tool execution and will be designed once both PRD 0004 and PRD 0008 are stable.

---

## Dependencies

- PRD 0001 (ModelConfig, `ModelaModel`, `create_completion_command`, usage logging)
- PRD 0003 (Anthropic and Ollama providers — registered in `ModelaModel` factory, ships alongside or after this PRD)
- PRD 0005 (resilience — retry/fallback wraps `agent.run()` in `create_completion_command`)
- `pydantic-ai` Python library (new dependency)
- `fastmcp` Python library (new dependency — MCP client)
- Redis (tool catalog caching, already present)
- Fernet encryption (already present in `app/security/crypto.py`)

---

## Success Criteria

- A request to a ModelConfig with `max_tool_rounds: 3` terminates after 3 tool-call rounds and returns `finish_reason: "max_rounds"` if the model keeps calling tools
- Tools from registered MCP servers are discovered, cached per-server, and passed to the LLM
- A tool execution timeout returns a structured error dict to the LLM (not a 502 to the caller)
- `tools` filter in the request correctly restricts available tools by server and/or tool name
- Every LLM call in the agentic loop is logged; the final `completion_requests` row has correct aggregate token counts and `tool_rounds`
- An MCP server that fails to load its tool catalog is gracefully skipped (warning logged; other servers unaffected)
- `stream: true` + tools available → `422 IncompatibleOptions`
- Admin can register, update, force-refresh, and delete MCP servers
- Credential values are never exposed in any API response after creation
- All new code has test coverage (unit + integration; MCP server calls mockable via `fastmcp` test transport)

---

## Testing

**ModelaModel with tools**
- Config params are applied to each round-trip in the agentic loop
- `log_completion_usage` is called once per LLM round-trip; aggregate `llm_calls` row has correct summed token counts and `tool_rounds`

**MCPToolExecutor**
- Successful tool call returns the tool output as a JSON string
- Tool execution timeout returns `{"error": "ToolTimeout", ...}` (not an exception)
- MCP server error returns `{"error": "ToolError", ...}` (not an exception)

**ToolCatalog**
- Tools are cached in Redis after first fetch; second call does not hit the MCP server
- Cache is invalidated on `refresh-tools` call
- Server that fails to load is skipped; remaining servers still return their tools

**MCPToolset**
- `get_tools` converts `MCPCatalogTool` list to pydantic-ai `ToolsetTool` list with correct `ToolDefinition`
- `call_tool` resolves `server_id` and `original_name` from qualified name and delegates to executor

**Tool filtering**
- `tools.servers` includes all tools from the named servers only
- `tools.tool_names` includes only the named qualified tools
- Both fields provided → union of matched tools
- `tools: {}` → no tools available, `Agent.run()` called with empty toolsets

**Agentic loop**
- Loop terminates at `max_tool_rounds` and returns `finish_reason: "max_rounds"`
- Loop terminates normally at `stop` and returns `finish_reason: "stop"`

**MCP credential**
- Credential data is stored encrypted; raw value not recoverable from DB column
- Credential value is absent from list and get API responses

**Incompatibility**
- `stream: true` with available tools returns `422 IncompatibleOptions`

**`MCPServerRepository`**
- `get_by_server_id` returns the record; returns `None` for unknown or soft-deleted ids
- `get_enabled` returns only rows with `enabled=True` and no `deleted_at`
- Soft-delete excludes the server from `get_enabled` results

**`MCPCredentialRepository`**
- `get(id)` returns the record; `encrypted_data` column contains non-plaintext bytes
- Soft-delete excludes the credential from subsequent `get` calls

**`MCPToolCatalogRepository`**
- `get_tools_for_request(filter=None)` returns tools from all enabled servers
- A server that raises an error during tool fetch is skipped; other servers' tools are still returned
- Filter by `servers=["github"]` returns only tools from that server

**Commands**
- `create_mcp_server_command`: persists all fields; `server_id` unique constraint raises on duplicate
- `update_mcp_server_command`: updates fields; disabling a server (`enabled=False`) excludes it from subsequent catalog fetches
- `delete_mcp_server_command`: soft-deletes; server no longer appears in `get_enabled`

**Routers (`mcp_servers_router`, `mcp_credentials_router`)**
- `POST /mcp-servers` returns `201` and the created record
- `GET /mcp-servers` excludes soft-deleted servers and returns paginated results
- `PUT /mcp-servers/{server_id}` with duplicate `server_id` returns `422`
- `POST /mcp-servers/{server_id}/refresh-tools` returns `202`; tool catalog cache is invalidated
- `DELETE /mcp-servers/{server_id}` returns `204`; server absent from subsequent list
- `POST /mcp-credentials` stores encrypted data; response contains `name` and `type` but not the credential value
- All MCP endpoints return `403` without `modela.mcp_server:*` / `modela.mcp_credential:*` permission
