# PRD 0019 — Product Knowledge Base & Default Tool Registry

## Problem Statement

LLMs served through modela have no way to ground answers in product-specific knowledge (what a product is, its purpose, internal concepts) beyond what's in a ModelConfig's system prompt or MCP-server tools. Operators want a shared, product-wide knowledge base of markdown documents that any ModelConfig can query, plus a general mechanism for opting individual ModelConfigs into a small set of modela-provided ("default") tools — `search_knowledge_base` being the first of several planned.

## Solution

Add a `KnowledgeDocument`/`KnowledgeChunk` model pair backed by pgvector for similarity search, a new `config_type="embedding"` on `ModelConfig` (with a generic JSON `params` column so chunking/embedding parameters are tunable without a deploy), a provider-agnostic embedding adapter interface parallel to the existing chat adapter registry, and a hardcoded, extensible built-in tool registry that ModelConfigs opt into via a plain list of tool names. Documents are chunked and embedded asynchronously via Celery, using whichever `ModelConfig` is the current default `embedding` config. The knowledge base is a single shared resource across all projects/accounts — not project-scoped. Knowledge documents and their chunks are hard-deleted because this data has no product requirement for restoration and retaining deleted embeddings would create unbounded storage growth.

Documents are ingested as [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)-style markdown: a YAML frontmatter block (metadata — tags, status, freshness, provenance) followed by a markdown body (the actual content). Ingestion splits the two; only the body is chunked and embedded, the frontmatter is stored as structured metadata and used for retrieval filtering (e.g. excluding stale documents).

## User Stories

1. As an operator, I want to upload/update/delete markdown documents via an API, so that the knowledge base stays current without touching code.
2. As an operator, I want a document's chunks to be fully replaced (delete + reingest) when I update its content, so that stale chunks never linger.
3. As an operator, I want to configure which embedding model/provider is used, so that I'm not locked into one vendor.
4. As an operator, I want to tune chunk size/overlap/strategy without a deployment, so that I can iterate on retrieval quality quickly.
5. As an operator, I want to swap the active embedding model/provider without a schema migration or dropped index, so that trying alternatives is cheap.
6. As an operator, I want to see the list of available built-in tools (name + description) via an endpoint, so that I can configure them in an admin UI.
7. As an operator, I want to opt a ModelConfig into one or more built-in tools by name, so that only relevant configs pay the extra tool/context overhead.
8. As an API consumer, I want the model to decide when to call `search_knowledge_base` (agentic tool call), so that retrieval only happens when the model judges it relevant.
9. As a developer, I want embedding chunks tagged with the embedding config that produced them, so that retrieval is scoped to the active config when operators follow the documented immutable-in-practice workflow.
10. As an operator, I want the admin UI to warn me before I change an embedding config that may already have indexed chunks, so that I understand that existing embeddings must be regenerated after changing the provider or model.
11. As an operator, I want to upload a document with YAML frontmatter (tags, status, freshness, sources) without that metadata polluting the embedded content, so that embeddings stay focused on the actual prose.
12. As an operator, I want stale documents (past their `stale_after` date, or marked `status: stale`) excluded from retrieval automatically, so that the model doesn't ground answers in outdated information.

## Implementation Decisions

### Scope: shared, product-wide knowledge base

One knowledge base, visible to every project/account. No per-project isolation in v1; administration is protected by global RBAC.

### Schema changes

**New table: `knowledge_documents`** (TimestampMixin only; this resource deliberately does not use `SoftDeleteMixin`)

| Column       | Type      | Notes                        |
| ------------ | --------- | ---------------------------- |
| `id`         | UUID (PK) |                               |
| `title`      | String    |                               |
| `content`    | Text      | Markdown body only (frontmatter stripped) |
| `metadata`   | JSONB     | Parsed YAML frontmatter (tags, status, stale_after, sources, generated, verified, etc.) — same generic-JSON pattern as `ModelConfig.params`, not embedded |
| `created_at` / `updated_at` | TIMESTAMPTZ | Standard timestamp mixin |

**New table: `knowledge_chunks`**

| Column               | Type                                | Notes                                                          |
| -------------------- | ----------------------------------- | --------------------------------------------------------------- |
| `id`                 | UUID (PK)                           |                                                                   |
| `document_id`        | UUID (FK → `knowledge_documents.id`)| Cascade delete                                                   |
| `chunk_index`        | Integer                             | Position within document                                         |
| `content`            | Text                                | Chunk text                                                       |
| `embedding`          | `vector` (pgvector, **no declared dimension**) | See "Vector schema" below                             |
| `embedding_config_id`| UUID (FK → `model_configs.id`)      | Which embedding ModelConfig produced this row                    |
| `chunk_params`       | JSONB                                | Snapshot of the chunk_size/overlap/strategy used, for auditability |
| `created_at`         | TIMESTAMPTZ                          |                                                                   |

Updating a document's content deletes all its `knowledge_chunks` and re-runs chunking + embedding against the current active embedding config — no incremental diffing. Deleting a document is a synchronous hard delete; the database FK cascade hard-deletes all of its chunks in the same transaction. There is no restore endpoint or retention period for knowledge documents.

**`model_configs` gains two columns:**

- `params` (JSONB, nullable) — generic, `config_type`-specific settings. For `config_type="embedding"`: `{chunk_size, chunk_overlap, strategy}`. Chosen over dedicated typed columns so future config types (and future tools) can add settings without a migration each time.
- `enabled_tools` (array of strings, nullable) — built-in tool names this config has opted into, e.g. `["search_knowledge_base"]`. Validated against the hardcoded tool registry at save time (unknown names rejected).

`config_type` Literal gains `"embedding"` alongside the existing `"chat" | "summary" | "generation" | "scan"`. `is_default` is already scoped per `config_type` (existing behavior) — the default `embedding`-type ModelConfig is what indexing and query-time embedding use.

Adding another default type exposes an existing ambiguity in chat completion resolution: `ModelConfigRepository.get_default()` is not scoped by `config_type`. As part of this feature, chat completion fallback must use `get_default_for_type("chat")`, and an explicitly selected ModelConfig whose `config_type` is not `"chat"` must be rejected with `422`. This prevents a default embedding config from being selected as a chat model.

**Correction (verified against the codebase, not a gap):** an earlier draft of this PRD claimed PRD 0012's required partial unique index on `is_default` was never built. That claim was wrong. The index already exists —
`alembic/versions/2026_05_18_0006_add_config_type_to_model_configs.py` creates a unique index on `model_configs (config_type)` filtered `WHERE is_default = true AND deleted_at IS NULL` — and `ModelConfigRepository.create()`/`update()` (via `create_model_config_command.py`/`update_model_config_command.py`) already catch the resulting `IntegrityError` and raise `ConflictError` (409). This protection already applies to every `config_type`, including the new `embedding` type, with no additional migration or command changes needed. The only addition this PRD makes here is a regression test proving two `config_type="embedding"` configs both marked `is_default=True` hit this existing 409 path.

### Embedding config mutation — accepted operational constraint

`embedding_config_id` identifies a ModelConfig row, but ModelConfigs are mutable. Changing the `provider` or `model` on a config that already produced chunks means old and new embeddings can share the same ID despite having incompatible provenance or dimensions. A dimension mismatch can make retrieval fail; a same-dimension model change can produce silently invalid rankings.

V1 deliberately does not introduce immutable embedding revisions or automatic reindex-on-config-change. Operators must create a new embedding ModelConfig when changing provider/model, set it as the default, and reingest the documents rather than mutating an in-use config. The `/model-configs/types` metadata for the `embedding` type must expose this warning, and the admin UI must display it prominently on embedding-config create/edit screens and require confirmation before changing `provider` or `model`. This is an operational safeguard, not a database guarantee.

### Embedding adapter interface

`BaseProviderAdapter` gains a synchronous, batch-capable method — **synchronous, not async**, matching `create_model()`'s existing convention and avoiding a mixed sync/async adapter interface:

```python
def create_embeddings(
    model_name: str,
    texts: list[str],
    api_key: str | None = None,
) -> list[list[float]]:
    ...
```

`model_name` comes from the resolved embedding ModelConfig, so the configured embedding model is passed explicitly rather than hidden inside the adapter. Indexing passes a batch of chunk texts; query-time retrieval passes a one-element list. The OpenAI adapter implements the method, while Anthropic and providers without an embeddings API raise `NotImplementedError`.

**Call-site contract:** the Celery indexing task (a sync context) calls `create_embeddings()` directly. The `search_knowledge_base` tool function is an `async def` (pydantic-ai supports async tools) but also calls `create_embeddings()` directly rather than via `asyncio.run()` — since the method is synchronous, there is no risk of `RuntimeError: asyncio.run() cannot be called from a running event loop`, which a mismatched async adapter method would have risked at exactly this integration point. If a provider's embeddings call is slow enough to matter inside the async tool path, batch multiple chunks per call (already required below) rather than making the method async.

Normal call sites omit `api_key`, and each adapter resolves its provider key from application settings, matching how `create_model()` is used today. The optional override is retained as a deliberate seam for tests and future BYOK support; it must not be persisted or logged by the adapter. This keeps embeddings provider-agnostic and addable without touching call sites, matching how chat providers are registered today (`app/inference/adapters/registry.py`). Embedding model selection remains a free-text ModelConfig field in v1; extending the chat-oriented provider catalog with discoverable embedding models is deferred until the admin UI needs it.

### Vector schema: undeclared dimension, no ANN index (documented decision)

**Decision:** the `embedding` column on `knowledge_chunks` does **not** declare a fixed pgvector dimension, and no ivfflat/hnsw index is built on it.

**Why:** pgvector only requires a fixed dimension when an ANN index is built on the column — an undeclared `vector` column can hold rows of varying length. Building an ANN index locks the column to one dimension; changing the active embedding model/provider (a stated requirement — see User Story 5) would otherwise force a drop/recreate of that index for a full re-embed. At current scale (dozens-hundreds of documents, low thousands of chunks), a sequential scan using pgvector's `<=>` cosine-distance operator is fast enough that an index isn't needed.

**How retrieval is scoped:** every chunk row carries `embedding_config_id`. Retrieval queries always filter `WHERE embedding_config_id = :active_embedding_config_id` before ranking by distance. This prevents comparison across distinct ModelConfig rows, but it cannot distinguish incompatible embeddings produced before and after an in-place mutation of the same row; operators must follow the workflow in "Embedding config mutation — accepted operational constraint."

**Revisit when:** corpus size grows enough that sequential scan latency becomes a problem. At that point, per-`embedding_config_id` partitioning with a dimension-specific ANN index per partition is the natural next step — deliberately deferred until there's evidence it's needed.

### Chunking strategy — dynamic, manually tuned

`chunk_size`, `chunk_overlap`, and `strategy` live in the active embedding ModelConfig's `params` JSONB, so they're editable via the existing ModelConfig admin API with no redeploy. Although persisted as JSONB, `params` is validated through a config-type-specific Pydantic schema. For embedding configs:

- `chunk_size` is measured in characters and must be between 256 and 8,192.
- `chunk_overlap` must be non-negative and strictly less than `chunk_size`.
- `strategy` must be one of the explicitly registered server-side strategies; unknown values are rejected.
- Raw document content is limited to 1 MiB and ingestion is rejected before enqueueing if the selected settings would produce more than 1,000 chunks.
- Retrieval uses a server-side default `top_k=5`, capped at 20 even if it later becomes caller-configurable.

Embedding requests should be batched where the provider supports batching rather than making one provider request per chunk. For v1, the "best" configuration is found by manual inspection of retrieved chunks against sample queries — no automated eval harness (recall@k/MRR against a golden query set) yet; see Out of Scope.

### API and authorization

Knowledge-document endpoints follow the existing global-domain RBAC pattern:

| Method | Path | Required permission | Behavior |
| ------ | ---- | ------------------- | -------- |
| `POST` | `/knowledge-documents` | `modela.knowledge_document:create` | Persist the document, then enqueue ingestion |
| `GET` | `/knowledge-documents` | `modela.knowledge_document:read` | List documents |
| `GET` | `/knowledge-documents/{id}` | `modela.knowledge_document:read` | Read one document |
| `PUT` | `/knowledge-documents/{id}` | `modela.knowledge_document:update` | Persist the update, then enqueue replacement ingestion |
| `DELETE` | `/knowledge-documents/{id}` | `modela.knowledge_document:delete` | Hard-delete the document and chunks synchronously |
| `GET` | `/tools` | `modela.tool:read` | List built-in tool metadata |

All endpoints also require an authenticated user. RBAC resolves against the global `"*"` domain because the knowledge base is product-wide. The absence of per-project isolation does not mean that ordinary authenticated users may administer the corpus.

### Built-in tool registry

A hardcoded, in-code registry (name → description/schema/implementation) of modela-provided tools, starting with `search_knowledge_base`. A `GET /tools` endpoint exposes the registry (name + description) for admin UI consumption. `ModelConfig.enabled_tools` stores a plain list of tool names (not per-tool parameter objects — per-tool tuning, e.g. `top_k`, falls back to server-side defaults for v1). At request time, the completion command's toolset assembly combines built-in tools (filtered by `enabled_tools`) with MCP-server tools (existing `mcp_servers` association) into one `toolsets` list for the pydantic-ai `Agent` — same integration point PRD 0011 wires MCP tools into.

### Ingestion: frontmatter/body split (OKF-style)

Uploaded documents follow the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) convention: a YAML frontmatter block delimited by `---` markers, followed by a markdown body. On create/update, before any chunking happens:

1. Parse and strip the frontmatter block; store it verbatim as `knowledge_documents.metadata` (JSONB).
2. Store the remaining markdown as `knowledge_documents.content`.
3. Frontmatter is never embedded — only `content` (the body) feeds the chunker. A document with no frontmatter is valid; `metadata` is simply empty.

**Frontmatter must be parsed with a safe YAML loader** (e.g. `yaml.safe_load()`, never `yaml.load()`'s default loader). `knowledge_document:create` is a content-management permission, not equivalent to full system-admin trust; an unsafe loader lets a YAML tag payload (e.g. `!!python/object/apply:os.system`) achieve arbitrary code execution on the modela server via document upload. A document whose frontmatter fails to parse (or resolves to a non-mapping type) is rejected at upload with `422`, not silently coerced to empty metadata.

Standard OKF fields worth relying on: `tags`, `status` (e.g. `current`/`stale`), `stale_after` (a date), `sources`, `generated`/`verified`. These aren't enforced by schema in v1 (arbitrary JSONB), but retrieval treats `status`/`stale_after` specially — see below.

### Indexing pipeline

Document create/update triggers an async Celery task (matching the existing `app/tasks/` `.delay()` pattern):

1. Delete existing `knowledge_chunks` for the document (on update).
2. Run the frontmatter/body split above.
3. Chunk `content` (body only) per the active embedding config's `params`.
4. Call the embedding adapter for each chunk.
5. Insert new `knowledge_chunks` rows tagged with `embedding_config_id` and a `chunk_params` snapshot.

The document row must commit before its task is enqueued. Document deletion is not a Celery task: it synchronously hard-deletes the document, and the FK cascade deletes its chunks in the same transaction.

V1 accepts that replacement ingestion is not atomic or generation-ordered. During an update, retrieval may temporarily return no chunks for that document, and overlapping updates may finish out of order so the last task to finish wins. This is acceptable at the expected scale and update frequency; callers should avoid overlapping edits. Atomic generation switching and stale-job suppression should be added if update frequency or corpus size grows.

### pgvector provisioning

Implementation requires both the Python `pgvector` package (including its SQLAlchemy type) and the PostgreSQL `vector` extension. The Alembic migration must execute `CREATE EXTENSION IF NOT EXISTS vector` before creating `knowledge_chunks`. CI must replace the current vanilla PostgreSQL service with a PostgreSQL 18 image that includes pgvector, pinned according to the project's dependency policy. Production rollout must verify that the database role may install the extension or that the managed database has enabled it before the application migration runs.

### Retrieval freshness filtering

`search_knowledge_base` excludes chunks whose parent document is stale: `metadata.status == "stale"` or `metadata.stale_after` is in the past. This is a simple predicate on `knowledge_documents.metadata`, evaluated alongside the existing `embedding_config_id` scoping — not a separate freshness pipeline or background job in v1 (nothing proactively flags documents as they cross `stale_after`; it's checked at query time).

### `search_knowledge_base` tool

Implemented as a pydantic-ai tool (agentic — the model decides when to call it, not always-on injection). At call time: embed the query using the active embedding ModelConfig, run a `<=>` distance query over `knowledge_chunks` filtered to that `embedding_config_id` and joined to `knowledge_documents` to exclude stale documents (see "Retrieval freshness filtering"), return top-k chunk contents.

## Testing Decisions

Follow existing patterns: `tests/routers/` with `create_client_fixture` for CRUD endpoints; integration tests for the Celery indexing task and the embedding adapter against a mocked provider client; repository tests for the `<=>` distance query scoped by `embedding_config_id`.

### Modules needing coverage

- **Knowledge document CRUD** — create/update enqueues the expected Celery task; delete performs a synchronous hard delete and cascade-deletes chunks without enqueueing a task.
- **Frontmatter parsing** — a document with valid YAML frontmatter splits correctly into `metadata` + `content`; a document with no frontmatter block is stored with empty `metadata` and the full body as `content`; malformed frontmatter fails predictably (rejected at upload, not silently swallowed); a document whose frontmatter contains a YAML tag payload (e.g. `!!python/object/apply:...`) is rejected/neutralized rather than executed, proving the parser uses a safe loader.
- **Freshness filtering** — a document with `status: stale` or a past `stale_after` is excluded from `search_knowledge_base` results; a document with no such fields is always eligible.
- **Embedding adapter** — OpenAI returns one vector per input in order for both single-item and multi-item batches; normal calls resolve the key from settings; an explicit key override is forwarded without being persisted or logged; Anthropic (or any adapter without support) raises `NotImplementedError` cleanly; `create_embeddings` is callable synchronously from both the Celery task and from within the async `search_knowledge_base` tool without raising an event-loop error.
- **`enabled_tools` validation** — ModelConfig save rejects unknown tool names; accepts any subset of registered names.
- **Retrieval scoping** — a query against `knowledge_chunks` with multiple `embedding_config_id`s present only returns/ranks chunks from the active config; never cross-compares mismatched vectors.
- **`search_knowledge_base` tool** — returns top-k results for a query; behaves sanely with zero documents indexed.
- **ModelConfig type isolation** — chat completion without a model resolves only the default `chat` config; selecting an `embedding` config explicitly is rejected.
- **One default per config_type** — concurrently (or sequentially) attempting to mark two ModelConfigs of the same `config_type` as default results in exactly one `is_default=True` row for that type; the second attempt (or a simulated race) surfaces `409`, not two simultaneous defaults.
- **Validation limits** — invalid overlap, unsupported strategy, oversized content, excess chunk count, and excessive `top_k` are rejected before expensive work starts.
- **Authorization** — each document/tool-registry endpoint rejects unauthenticated callers and callers lacking the required global RBAC permission.
- **Migration/runtime** — the migration enables pgvector and runs in the same pgvector-capable PostgreSQL image used by CI.

## Out of Scope

- Automated retrieval evaluation (golden query set, recall@k/MRR) — v1 tuning is manual/eyeballed; a fast-follow if manual tuning proves insufficient.
- Per-tool parameter objects on `enabled_tools` (e.g. per-config `top_k`) — plain name list only for v1.
- Document versioning, draft/review workflow — simple CRUD only.
- Soft deletion or restoration of knowledge documents — deletes are permanent and cascade to chunks.
- Per-project knowledge base scoping/access control — single shared knowledge base for all projects.
- ANN indexing / per-embedding-config partitioning — deferred until sequential scan latency is a proven problem.
- Always-on retrieval injection mode — agentic tool-call only.
- Immutable embedding-config revisions, atomic generation switching, and stale-job suppression — operators avoid mutating in-use configs and overlapping document updates in v1.
- Schema-enforced frontmatter fields — `metadata` is arbitrary JSONB in v1; no validation that `tags`/`status`/`stale_after`/`sources` conform to a fixed shape beyond what `status`/`stale_after` filtering reads.
- Proactive staleness notifications (e.g. alerting an operator when a document crosses `stale_after`) — freshness is only checked reactively at query time.
- Rendering the OKF concept graph (cross-document links, backlinks, the Cytoscape-based viewer from the OKF repo) — links in the markdown body are stored as plain text, not parsed into a link graph.

## Further Notes

The biggest open risk is retrieval quality (chunking strategy, top-k, ranking), not the plumbing — the schema, adapter, and tool-registry mechanics all follow patterns already established in the codebase (PRD 0011's ModelConfig↔MCPServer association, PRD 0008's tool loop). Recommended first implementation slice: the embedding `config_type` + adapter interface, and a minimal chunk/embed/search path against a handful of real documents, before building out the full `enabled_tools` UI/registry surface — validate retrieval quality early since it's the part hardest to estimate up front.
