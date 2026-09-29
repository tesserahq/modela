## Problem Statement

Modela's knowledge-base ingestion chunks documents with a single hard-coded strategy (`fixed_size`): it slices raw character windows with a sliding overlap, with no awareness of Markdown structure. This produces chunks that cut words, sentences, paragraphs, lists, code fences, tables, or a section off from its own heading, and it stores no offsets, heading lineage, or token counts — so there is no way to inspect, debug, or improve retrieval quality.

Separately, the chunking algorithm is baked directly into the indexing task and into one shared, all-strategies-must-fit config schema (`EmbeddingConfigParams`). There is no seam: adding a second, better chunking algorithm today means growing the same function and the same schema, the same way every embedding/model provider is *not* built — Modela already solved this exact shape of problem for inference providers (`app/inference/adapters/`), where swapping OpenAI for Anthropic, or adding a new provider, never touches the calling code. Chunking has no equivalent seam, so any future change to how documents are split (a new library, a smarter algorithm, per-provider tuning) risks touching the indexing task, the config schema, and the chunk model all at once.

## Solution

Introduce a **chunk provider** abstraction, modeled directly on the existing inference-provider-adapter pattern: a `BaseChunkProvider` interface, a registry of interchangeable implementations keyed by a versioned strategy name, and a thin factory used by the indexing task. Each provider owns its own chunking algorithm, its own tokenizer/encoding, and its own parameter schema (valid ranges, units, defaults) — nothing about one provider's internals leaks into another's, or into the calling code.

Ship two providers behind this seam from day one:

- `fixed_size` — the existing character-sliding-window strategy, moved behind the provider interface. The migration also removes the fully redundant trailing chunk produced when the final overlap window contains no new content.
- `markdown_recursive_v1` — a new, token-budgeted, Markdown-structure-aware strategy (backed by `semantic-text-splitter`, per prior research) that splits at heading boundaries, keeps blocks/paragraphs/sentences intact where possible, and returns heading lineage and character offsets for every chunk.

This is a fresh-start rollout: there are no indexed documents to preserve, and any existing embedding configs will be deleted and recreated during deployment. New embedding configs default to `markdown_recursive_v1`; no compatibility path for the old `strategy` field is required. The richer output each `markdown_recursive_v1` chunk produces (heading path, offsets, and raw token count) is persisted on `knowledge_chunks`, along with a content hash, the exact heading-enriched string sent to the embedding model, its token count, and the effective tokenizer/splitter configuration so results are debuggable and reproducible.

## User Stories

1. As a platform engineer, I want chunking implemented behind an interface (like inference providers), so that adding a new chunking algorithm never requires touching the indexing task or other providers' code.
2. As a platform engineer, I want each chunk provider to declare and validate its own parameters, so that a token-based provider and a character-based provider can each have correct, independent valid ranges and defaults without compromising on one shared schema.
3. As a platform engineer, I want chunk providers registered in a single lookup table keyed by a versioned strategy name, so that selecting, listing, and adding providers follows the same mental model as `PROVIDER_REGISTRY` for inference.
4. As a platform engineer, I want an invalid `chunking_provider` value rejected when an embedding config is created or updated, so that a typo is caught immediately instead of failing an async reindex task later.
5. As a platform engineer, I want new embedding configs to default to `markdown_recursive_v1`, so that new knowledge bases get better chunk quality without anyone having to discover and opt into it.
6. As a developer debugging retrieval quality, I want each stored chunk to record its heading path, so that I can tell which section of a document a retrieved chunk came from.
7. As a developer debugging retrieval quality, I want each stored chunk to record its exact character offsets in the source document, so that I can trace a chunk back to its precise source location.
8. As a developer debugging retrieval quality, I want each stored chunk to record its token count, so that I can validate chunk sizes against embedding-model input limits and reason about cost.
9. As a developer debugging retrieval quality, I want each stored chunk to record a content hash of its raw excerpt, so that I can detect exact duplicate chunks across a document or across reindexes.
10. As a developer debugging retrieval quality, I want each stored chunk to record the exact string that was sent to the embedding model (heading-enriched, not just the raw body) and its token count, so that I can audit what the embedding actually represents and validate it against the embedding model's input limit.
11. As a platform engineer, I want `markdown_recursive_v1` to keep Markdown blocks, paragraphs, sentences, and words intact wherever the token budget allows, so that chunks stop cutting words, sentences, or structural elements mid-way.
12. As a platform engineer, I want `markdown_recursive_v1` to never let overlap cross a heading boundary, so that a chunk's context never bleeds in unrelated content from a different section.
13. As a platform engineer, I want a global maximum-chunks-per-document limit enforced regardless of which provider ran, so that one runaway provider or pathological document cannot produce unbounded rows.
14. As an API consumer of the provider catalog, I want to list available chunk providers the same way I can list inference providers, so that clients can build config UIs without hard-coding provider names.
15. As a test author, I want each chunk provider's `chunk()` method testable as a pure function with no I/O, so that provider tests stay as simple as today's `test_chunking.py`, without mocking HTTP or SDK boundaries.
16. As a platform engineer, I want chunk generation and embedding requests bounded before expensive work grows beyond provider or application limits, so that pathological content or configuration fails predictably without exhausting worker resources.

## Implementation Decisions

**Module layout** (new package `app/services/knowledge/chunk_providers/`, mirroring `app/inference/adapters/`):

- `base.py` — `BaseChunkProvider` ABC. Class-level `provider_id: str`. Each concrete provider declares its own Pydantic parameter schema (equivalent role to `ProviderParameters` for inference adapters) and implements `chunk(content: str, params: <provider's own params model>, *, max_chunks: int) -> list[ChunkDraft]`. A provider must stop and raise `InvalidParameterError` as soon as it would emit chunk `max_chunks + 1`; callers do not rely only on checking the length of a fully materialized result. Providers are stateless singletons, instantiated with no constructor args, same as `OpenAIProviderAdapter()`/`AnthropicProviderAdapter()`.
- `chunk_draft.py` — the `ChunkDraft` value object, shared by all providers: `content` (exact source excerpt), `heading_path` (tuple of strings, empty for non-structural providers), `start_offset`, `end_offset`, `token_count`.
- `fixed_size.py` — migrates the existing sliding-window logic behind the interface (same step calculation and slicing), with a char-based params schema (`chunk_size`, `chunk_overlap` in characters) preserving today's `256–8192` / `overlap < size` constraints, and `heading_path=()` on every chunk since it has no structural awareness. It does not emit a final chunk whose content is wholly contained in the preceding chunk. Its `token_count` remains observability metadata measured with `cl100k_base`; tokens do not control its character-based boundaries.
- `markdown_recursive_v1.py` — splits the document into heading-scoped sections, then wraps `semantic_text_splitter.MarkdownSplitter` for each section, with a token-based params schema (`chunk_size`, `chunk_overlap` in tokens; defaults 512 / 64, with explicit minimum and maximum values). It uses the `cl100k_base` tiktoken encoding used by Modela's currently supported OpenAI embedding models. It obtains each chunk's relative character offset from `MarkdownSplitter.chunk_indices()` and adds the section's source offset; it never reconstructs offsets with `str.find()`. Every draft must satisfy `content[start_offset:end_offset] == draft.content`. Results are accumulated section by section so the provider can abort immediately on chunk `max_chunks + 1`, and overlap never crosses a heading boundary.
- `registry.py` — `CHUNK_PROVIDER_REGISTRY: dict[str, BaseChunkProvider]` of pre-instantiated singletons keyed by versioned strategy name (`"fixed_size"`, `"markdown_recursive_v1"`), and `get_chunk_provider(name: str) -> BaseChunkProvider` raising `ValueError` on an unknown key — same shape as `get_adapter()` in `app/inference/adapters/registry.py`.

**Naming convention**: registry keys are versioned strategy names, not library names (e.g. `markdown_recursive_v1`, not `semantic_text_splitter`). This decouples the stored/config value from the backing library — a future library swap that preserves equivalent behavior doesn't require a config migration, and a real behavior change gets a new versioned name (`markdown_recursive_v2`) rather than silently changing what an existing name produces.

**Config schema (`app/schemas/embedding_config_params.py`)**:

- Field `strategy` is renamed to `chunking_provider`.
- The single shared `EmbeddingConfigParams` model (currently enforcing one global `chunk_size`/`chunk_overlap`/`EMBEDDING_CHUNK_STRATEGIES` rule for every strategy) is replaced: `chunking_provider` is validated against `CHUNK_PROVIDER_REGISTRY` at create/update time (fail fast — an unknown value is rejected immediately, not deferred to indexing time as the inference `provider` field currently is). The remaining params are parsed and validated using the selected provider's own parameter schema, so `fixed_size` keeps its char-based range and `markdown_recursive_v1` gets its own token-based range/defaults, with neither constraining the other.
- This deployment does not preserve old embedding-config JSON. Before the new schema is used, existing embedding configs are deleted and recreated; there are no indexed documents requiring migration. The old `strategy` key is rejected rather than treated as an alias. New embedding configs may omit `params` entirely or omit `chunking_provider`, `chunk_size`, and `chunk_overlap` within it; create/update validation persists the selected provider schema's normalized values, with `chunking_provider: "markdown_recursive_v1"` and that provider's defaults.

**Indexing task (`app/tasks/index_knowledge_document.py`)**:

- Resolves the provider via `get_chunk_provider(config.chunking_provider)` instead of calling `chunk_text` directly.
- The global `MAX_CHUNKS_PER_DOCUMENT` cap remains a cross-provider invariant. The task passes it into the provider so generation stops at the limit, then defensively verifies the returned list does not exceed it.
- Contextualization (building the string actually sent for embedding — heading breadcrumb + chunk body, never the document title) is shared, provider-agnostic code in the task, not owned by any individual provider. Title-only document updates therefore continue not to trigger reindexing.
- After contextualization, the task counts each final `embedding_content` with the encoding selected for the active embedding model and rejects any input over that model's limit before making an API request. `chunk_size` remains the raw-body target; it is not treated as proof that the contextualized string fits.
- Computes and stores `content_hash` (hash of the raw chunk excerpt), `embedding_content` (the actual string embedded), `token_count` (raw excerpt), and `embedding_token_count` (final embedding input) per chunk.

**Data model (`app/models/knowledge_chunk.py`)**: new columns — `heading_path` (JSONB), `start_offset` (int), `end_offset` (int), `token_count` (int), `embedding_token_count` (int), `content_hash` (string), and `embedding_content` (text). `chunk_params` is retained, but stores the normalized effective configuration rather than only the submitted JSON: `chunking_provider`, provider params, `size_unit`, tokenizer/encoding ID, splitter name and installed version, and contextualization version (`heading_v1`). A new Alembic migration adds these columns; no existing chunk backfill is required because this is a fresh-start rollout with no indexed documents.

**Embedding batching (`app/inference/adapters/`)**: batching remains encapsulated behind `BaseProviderAdapter.create_embeddings(...)`; the indexing task continues to make one logical call with an ordered list. `OpenAIProviderAdapter` partitions that list into requests bounded by both input count and aggregate tokens, using a safety margin below OpenAI's published request limits, concatenates returned vectors in input order, and raises if any subrequest fails or returns the wrong number of vectors. Because all embedding calls finish before chunk replacement starts, a partial batch failure leaves the prior usable index intact. Future adapters own their own provider-specific batching limits without changing the indexing task.

**Dependency and behavior pinning**: add direct, exact runtime dependencies for `semantic-text-splitter` and `tiktoken`, and commit the resolved lockfile. The effective library and tokenizer versions are snapshotted in `chunk_params`. Any deliberate change that can alter chunk boundaries, offset semantics, tokenization, or contextualization creates a new provider/contextualization version rather than silently changing `markdown_recursive_v1` output.

**`chunking.py` retirement**: the current module (`_fixed_size`, `_STRATEGIES`, `chunk_text`) is removed once `fixed_size.py` and the registry replace its role; the `MAX_CHUNKS_PER_DOCUMENT` constant and its enforcement move to the indexing task as described above.

**Provider catalog exposure**: chunk providers are listed the same way inference providers are (mirroring `app/routers/providers_router.py`'s `list_providers`), so config-building clients can enumerate valid `chunking_provider` values without hard-coding them.

## Testing Decisions

A good test here exercises observable behavior — given input content and params, what chunks (and their offsets/heading paths/token counts) come out — not internal call sequencing. Prior art: `tests/app/services/knowledge/test_chunking.py` already tests `chunk_text` this way (exact slice boundaries, empty-content edge case, invalid-strategy error, max-chunks cap) with no mocking, since the current implementation has no I/O; that same no-mocking style should carry over since both providers remain pure/no-I/O (`markdown_recursive_v1` does local, deterministic CommonMark parsing and local tokenization — no network calls).

Modules to test, per the agreed module sketch:

- `fixed_size.py` — same cases `test_chunking.py` already covers (exact boundaries and empty content), plus an explicit assertion that a final overlap-only window is not emitted, now exercised through the provider interface instead of the retired module-level function.
- `markdown_recursive_v1.py` — heading-boundary splitting, that overlap never crosses a heading boundary, oversized-section recursive splitting (block/paragraph/sentence/word fallback), preservation of code fences/tables when they fit within budget, correct `heading_path`/offsets/`token_count` on returned `ChunkDraft`s, and behavior on malformed/plain (non-Markdown) input. Offset cases include repeated identical paragraphs, Unicode, trimmed whitespace, and overlap, and assert exact source-slice equality. A limit test proves generation stops when chunk `MAX_CHUNKS_PER_DOCUMENT + 1` would be emitted.
- `registry.py` — `get_chunk_provider` returns the correct singleton for a known key and raises `ValueError` for an unknown one, mirroring the existing adapter-registry test coverage style referenced for `PROVIDER_REGISTRY`.
- `embedding_config_params.py` validation changes — `chunking_provider` rejected at validation time when unknown; `fixed_size` and `markdown_recursive_v1` each validated against their own params schema (valid char range for one, valid token range for the other) without either constraining the other.
- `OpenAIProviderAdapter.create_embeddings` — multiple physical batches are issued when either the item or aggregate-token threshold is reached; returned vectors preserve input order; a short response or failure from any batch raises. The indexing-task test verifies a later-batch failure leaves the previous chunks untouched.
- Contextualized embedding input — headings are included but document titles are not; `embedding_token_count` matches the exact stored input; an input exceeding the active model's limit is rejected before the adapter is called.

Out of scope for dedicated tests in this PRD (covered indirectly through the focused integration cases above, or already exercised at a higher level per the codebase survey): additional indexing-task end-to-end coverage unrelated to chunk providers, and the provider-catalog listing endpoint (follows the same pattern as the existing inference `list_providers` test).

## Out of Scope

- Anthropic's Contextual Retrieval (LLM-generated per-chunk context blurbs) — the static heading-breadcrumb prefix is the near-term contextualization approach; an LLM-generated variant is a deliberate future consideration, not part of this PRD.
- Late chunking (embed-then-pool) — does not fit the `ChunkProvider.chunk(...) -> ChunkDraft[]` seam this PRD builds; would need its own architectural treatment if ever pursued.
- `parent_chunk_id` / small-to-big retrieval — no consumer exists yet; deferred until retrieval work actually needs it.
- Any other candidate libraries surveyed in prior research (`langchain-text-splitters`, `semchunk`, Chunklet-py, ChunkNorris, Chonkie, LlamaIndex, Docling, Unstructured, wtpsplit, Chonky) as additional providers — the registry/interface built here makes adding any of them a future, isolated change, not part of this PRD.
- Retrieval-side changes (`search.py`) beyond what's needed to keep it working — returning a structured result (content, heading path, offsets, score) instead of `list[str]` is future work noted in prior research, not required here.
- Backward compatibility or data migration for existing embedding configs/chunks — deployment starts fresh by deleting and recreating any embedding configs, and there are no indexed documents to preserve.
- A UI or admin surface for choosing/comparing chunk providers — this PRD is the backend seam and the two initial providers only.

## Further Notes

This PRD directly extends `docs/knowledge-base-chunking-research.md`, which contains the fuller comparison of chunking libraries/techniques, the risk analysis (tokenization mismatch, dependency compatibility, context-prefix dominance, Markdown parser edge cases, migration cost, framework leakage), and the staged-adoption rationale behind picking `semantic-text-splitter` as `markdown_recursive_v1`'s backing library. That document remains the reference for *why* this specific algorithm and library were chosen; this PRD covers *how* it's integrated behind a pluggable seam.

The codebase does not have one single consistent "pluggable provider" house style today — inference uses ABC+registry, credentials use enum+if/elif dispatch, and MCP client construction is a single non-branching factory function. This PRD deliberately extends the ABC+registry style to a second domain because it's the most mature of the three and the one explicitly referenced as the model to follow; it is not claiming that style is already a universal convention.
