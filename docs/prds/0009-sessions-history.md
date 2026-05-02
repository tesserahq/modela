# PRD 0009 — Sessions & Conversation History

## Overview

This phase introduces server-side session storage and conversation history management. When a caller provides a `session_id`, Modela loads the session's prior message history, appends the new user message, runs the completion (including any agentic tool loops from PRD 0008), and stores the updated history. The caller only sends the new message; Modela owns the context window. The stateless path (no `session_id`) is fully unchanged.

---

## Goals

- Store conversation history server-side, keyed by a caller-managed `session_id`
- Automatically inject session history before the incoming message on each request
- Write completed turns (user + assistant messages, including tool call/result messages) back to the session after each request
- Support session compaction: summarize old messages to stay within context limits
- Expose session CRUD endpoints for browsing and managing history
- Include `session_id` in usage records for attribution

---

## Non-Goals

- Session ownership or access-control scoping (session_id is caller-managed; Modela does not validate who owns it)
- Automatic session creation without an explicit `session_id` (callers always supply their own ID)
- Session branching or forking
- Multi-participant / multi-user sessions
- Session search or full-text indexing of message history

---

## Background

PRD 0008 enables multi-round agentic tool use. Sessions make those conversations persistent: a caller can pick up where they left off by passing the same `session_id`. Without sessions, every request is independent and the caller must send the full message history themselves. With sessions, Modela maintains the context and the caller only sends new messages.

Session IDs are caller-managed strings. Modela does not generate or validate them — any string the caller supplies becomes the key. This keeps the integration simple: callers can use their own internal identifiers (user IDs, ticket IDs, thread IDs) as session keys without a separate session-creation step.

---

## Data Model

### Table: `sessions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `session_id` | VARCHAR(255) | Caller-managed identifier. Unique among non-deleted rows. |
| `project_id` | VARCHAR | From request context at first use |
| `model_config_slug` | VARCHAR | Last ModelConfig slug used in this session |
| `last_message_at` | TIMESTAMPTZ | Updated after every turn |
| `summary` | TEXT | Compacted summary of older messages. `null` if not yet compacted. |
| `created_at` | TIMESTAMPTZ | Auto-set on first use |
| `updated_at` | TIMESTAMPTZ | Auto-updated |
| `deleted_at` | TIMESTAMPTZ | Soft delete |

**Constraint:** `session_id` unique among non-deleted rows.

### Table: `session_messages`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `session_id` | UUID (FK) | References `sessions.id` |
| `role` | VARCHAR(50) | `user`, `assistant`, `tool`, `system` |
| `content` | TEXT | Message content (text). `null` for assistant messages that only contain tool calls. |
| `tool_calls` | JSONB | Tool call blocks for `role: assistant` messages (from PRD 0008 agentic loops). `null` otherwise. |
| `tool_call_id` | VARCHAR | For `role: tool` messages: the ID of the tool call this result responds to. |
| `created_at` | TIMESTAMPTZ | Auto-set |

Messages are ordered by `created_at` for history reconstruction.

---

## API Changes to POST /chat/completions

New optional `session_id` field in the request body:

```json
{
  "model": "openai-gpt-4o",
  "messages": [{ "role": "user", "content": "What was my last question?" }],
  "session_id": "my-conversation-abc123"
}
```

**Resolution flow when `session_id` is present:**

1. Load session by `session_id`, or create a new session if it does not exist
2. Load session message history (ordered by `created_at`, last 100 messages)
3. If `sessions.summary` is set: prepend as `{"role": "system", "content": "Summary of earlier conversation: <summary>"}`
4. Build final messages array: `[summary_system_message?, ...history, ...request.messages]`
5. Run completion using the assembled messages (agentic loop if tools available, PRD 0008)
6. Write turn to session:
   - All messages from `request.messages` (typically one user message)
   - All assistant and tool messages produced during the completion (including mid-loop tool calls and results)
7. Update `sessions.last_message_at` and `sessions.model_config_slug`
8. Return response to caller (unchanged from non-session path)

When `session_id` is absent, the request is processed exactly as before — no session lookup, no history injection, no storage.

**Auto-creation:** if `session_id` is provided but no session exists with that ID, a new session is created transparently. The caller does not need to pre-create sessions.

---

## Session CRUD API

RBAC: `modela.session:*` for all endpoints.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Explicitly create a session (optional; sessions are also auto-created on first use) |
| `GET` | `/sessions/{session_id}` | Get session metadata |
| `GET` | `/sessions/{session_id}/messages` | Paginated message history (ordered by `created_at`) |
| `DELETE` | `/sessions/{session_id}` | Soft-delete the session |
| `POST` | `/sessions/{session_id}/compact` | Trigger compaction |

**`POST /sessions` request body:**

```json
{
  "session_id": "my-conversation-abc123"
}
```

**`GET /sessions/{session_id}/messages` response:**

```json
{
  "items": [
    { "id": "uuid", "role": "user", "content": "Hello", "created_at": "..." },
    { "id": "uuid", "role": "assistant", "content": "Hi! How can I help?", "created_at": "..." }
  ],
  "total": 2,
  "page": 1,
  "size": 50
}
```

---

## Session Compaction

Sessions grow unbounded over long conversations and will eventually exceed the model's context window. Compaction summarizes old messages to keep the window manageable.

**Compaction flow:**

1. Load all messages in the session except the last `keep_last_n` (default: 20)
2. Ask the session's `model_config_slug` LLM to summarize the older messages into a concise paragraph (internal call — not logged as a user completion request)
3. Store the summary in `sessions.summary`
4. Hard-delete the compacted messages (they are preserved only in the summary)
5. On next request: summary is prepended as a system message before the remaining history

**Trigger conditions:**

- **Manual:** `POST /sessions/{session_id}/compact`
- **Automatic:** when a session exceeds `SESSION_AUTO_COMPACT_THRESHOLD` messages (app setting, default: 100). Auto-compaction runs as a Celery task after the turn is written, non-blocking.

**`keep_last_n` default: 20.** This is a system-level default; per-session override is not supported in this phase.

---

## `SessionManager` Facade

`SessionManager` is the single interface for all session operations called from the completion endpoint. It wraps the underlying repositories:

```python
class SessionManager:
    def get_or_create(self, session_id: str, project_id: str) -> Session: ...
    def get_history_for_llm(self, session: Session, limit: int = 100) -> list[dict]: ...
    def add_turn(self, session: Session, request_messages: list, response_messages: list) -> None: ...
    def compact(self, session: Session, keep_last_n: int = 20) -> None: ...
```

`get_history_for_llm` returns messages in OpenAI role format, with tool call/result fields preserved for agentic sessions (PRD 0008). The summary system message is prepended when present.

---

## Usage Logging

New column on `completion_requests`:

| Column | Type | Notes |
|--------|------|-------|
| `session_id` | VARCHAR(255) | Session ID if the request was part of a session. `null` for stateless requests. |

---

## Dependencies

- PRD 0001 (completion endpoint, project_id context, usage logging)
- PRD 0008 (tool_calls and tool result messages in session history; agentic loop produces the messages that get stored)

---

## Success Criteria

- A second request with the same `session_id` receives the prior conversation history automatically
- Session history persists across multiple requests and worker processes (stored in Postgres)
- Stateless requests (no `session_id`) are completely unaffected
- Tool call and tool result messages from agentic sessions (PRD 0008) are stored and replayed correctly
- Compaction reduces message count, stores a summary, and the summary is prepended on next request
- Auto-compaction triggers when session exceeds `SESSION_AUTO_COMPACT_THRESHOLD` without blocking the response
- Soft-deleting a session means subsequent requests with that `session_id` start a fresh session
- `GET /sessions/{session_id}/messages` returns correctly ordered, paginated history
- `session_id` is recorded in `completion_requests` usage records
- All session operations have test coverage (unit + integration)

---

## Testing

**Session lifecycle**
- First request with a `session_id` auto-creates the session
- Second request with the same `session_id` receives prior history injected before the incoming message
- Stateless request (no `session_id`) is unaffected and does not create a session

**History injection**
- Prior messages appear in the correct order before the incoming message
- When `sessions.summary` is set, it is prepended as a system message before the history
- History is limited to the last 100 messages

**Turn storage**
- User message and assistant response are both written to `session_messages` after a successful request
- Tool call and tool result messages from agentic requests (PRD 0008) are stored with `tool_calls` / `tool_call_id` populated
- `session.last_message_at` and `session.model_config_slug` are updated after each turn

**Compaction**
- Manual `POST /sessions/{session_id}/compact` stores a summary and hard-deletes messages older than `keep_last_n`
- Next request after compaction prepends the summary as a system message
- Auto-compaction triggers when message count exceeds `SESSION_AUTO_COMPACT_THRESHOLD`

**Soft delete**
- `DELETE /sessions/{session_id}` soft-deletes the session
- Subsequent request with the same `session_id` auto-creates a new session (no history carried over)

**`llm_calls` attribution**
- `session_id` is recorded on the `llm_calls` row when a session is active
- `session_id` is null on `llm_calls` rows for stateless requests

**`SessionRepository`**
- `get_or_create(session_id)` returns an existing session on the second call without creating a duplicate
- `get_by_session_id` returns `None` for a soft-deleted session
- Unique constraint: two concurrent creates with the same `session_id` do not produce duplicate rows

**`SessionMessageRepository`**
- `create_message` persists `role`, `content`, `tool_calls`, and `tool_call_id` correctly
- `get_messages(session_id, limit=100)` returns messages ordered by `created_at` ascending
- `hard_delete_before(session_id, created_at_cutoff)` removes rows permanently (not soft-delete); subsequent query does not return them

**`SessionManager`**
- `get_history_for_llm` returns messages in `[{"role": ..., "content": ...}]` format ordered oldest-first
- `get_history_for_llm` prepends the summary system message when `session.summary` is set
- `get_history_for_llm` caps output at `limit` most recent messages
- `add_turn` writes all request messages and all response messages as separate `session_messages` rows
- `compact` stores a non-empty summary on `session.summary` and hard-deletes older messages, keeping exactly `keep_last_n`

**Router (`sessions_router`)**
- `POST /sessions` with a duplicate `session_id` returns `409`
- `GET /sessions/{session_id}/messages` returns paginated results ordered by `created_at`
- `DELETE /sessions/{session_id}` soft-deletes; subsequent `GET /sessions/{session_id}` returns `404`
- `POST /sessions/{session_id}/compact` returns `202` and summary is set on the session row
- All session endpoints return `403` without `modela.session:*` permission
