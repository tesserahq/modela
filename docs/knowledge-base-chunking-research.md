# Knowledge-base chunking research

Date: 2026-09-05

## Executive summary

Modela should replace raw character windows with a **Markdown-aware, token-budgeted chunking strategy**. The first production version should split a document into heading-scoped sections, recursively split oversized sections at block/paragraph/sentence/word boundaries, and embed each chunk with a compact document-title and heading-path prefix. The original chunk body should remain separate from the contextualized embedding input.

The best immediate library candidates are `langchain-text-splitters`, `semantic-text-splitter`, and `semchunk`:

- `langchain-text-splitters` is the easiest route to explicit heading metadata because `MarkdownHeaderTextSplitter` groups content under configured headers and emits those headers as metadata; `RecursiveCharacterTextSplitter` then provides a configurable fallback hierarchy ([official Markdown documentation](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter), [official recursive splitter documentation](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)).
- `semantic-text-splitter` is the best lightweight alternative. Its `MarkdownSplitter` parses CommonMark and chooses the largest fitting semantic units across headings, block elements, inline elements, Unicode sentences, words, graphemes, and characters; it supports character, Hugging Face-tokenizer, tiktoken, and callback sizing ([upstream README](https://github.com/benbrandt/text-splitter#method), [PyPI](https://pypi.org/project/semantic-text-splitter/)).
- `semchunk` is another strong lightweight candidate. It recursively chooses generic text boundaries from newline and whitespace runs down through sentence/clause punctuation and characters, supports arbitrary token counters, returns exact character offsets, and has only `tqdm` as an unconditional dependency ([upstream algorithm and API](https://github.com/isaacus-dev/semchunk#how-it-works-), [upstream package metadata](https://github.com/isaacus-dev/semchunk/blob/main/pyproject.toml)).

**Given dependency footprint as the deciding priority, `semantic-text-splitter` is the primary recommendation over `semchunk` and `langchain-text-splitters`.** Both `semantic-text-splitter` and `semchunk` are comparably light (a thin Rust binding vs. a small pure-Python package with one unconditional dependency), which makes footprint a wash between them. The deciding factor is that only `semantic-text-splitter` parses real CommonMark structure—headings, code fences, lists, tables—while `semchunk` falls back to generic whitespace/punctuation boundaries on plain-string input. For a Markdown-native knowledge base, that structural awareness is worth more than `semchunk`'s exact-offset and arbitrary-tokenizer conveniences, and both approaches require the same amount of Modela-owned code to derive heading-path metadata. `langchain-text-splitters` remains the fallback if a future spike shows its built-in heading metadata saves meaningfully more implementation effort than its added abstraction and dependency weight cost. Do not make embedding-based semantic chunking—including Semchunk's optional Isaacus-backed mode—the default until an offline retrieval evaluation shows a material gain.

## Current Modela behavior

The present ingestion path is intentionally small:

1. [`frontmatter.py`](../app/services/knowledge/frontmatter.py) separates YAML frontmatter from the Markdown/text body. Only the body is chunked and embedded.
2. [`chunking.py`](../app/services/knowledge/chunking.py) supports only `fixed_size`. It advances by `chunk_size - chunk_overlap` and slices Python strings, so size and overlap are characters rather than model tokens.
3. [`index_knowledge_document.py`](../app/tasks/index_knowledge_document.py) reads chunk parameters from the active embedding `ModelConfig`, creates every chunk, sends all chunk strings in one embedding call, then transactionally replaces the previous rows.
4. [`knowledge_chunk.py`](../app/models/knowledge_chunk.py) stores only the body text, ordinal, vector, embedding-config ID, and a JSON parameter snapshot.
5. [`search.py`](../app/services/knowledge/search.py) embeds the query with the active embedding config, ranks by cosine distance, and returns only the top chunk bodies (default five, hard maximum twenty).

The configuration schema currently allows a 256–8,192 character `chunk_size`, requires overlap to be smaller than size, and accepts only `fixed_size` ([`embedding_config_params.py`](../app/schemas/embedding_config_params.py)). Input is capped at 1 MiB of UTF-8 ([`knowledge_document.py`](../app/schemas/knowledge_document.py)), and chunking refuses more than 1,000 chunks per document.

### Consequences

- A boundary may cut a word, sentence, paragraph, Markdown list, code fence, table, or section from its heading.
- Character limits do not reliably predict embedding-model token limits across languages or content types.
- Blind overlap can duplicate irrelevant text and can cross topical boundaries.
- A trailing iteration can be wholly redundant. For example, a 300-character body with size 300 and overlap 50 produces chunks `[0:300]` and `[250:300]`.
- Frontmatter, document title, and heading lineage do not inform the embedding, even though they may disambiguate a short excerpt.
- There are no offsets or stable hashes for provenance, highlighting, deduplication, or evaluation.
- A single embedding request for up to 1,000 chunks assumes every provider accepts that batch size.
- Since reindex is asynchronous and replacement has no content-version guard, an older task can overwrite a newer index if tasks overlap in the wrong order.

## Candidate libraries

### Comparison

| Library | Context-preserving approach | Fit for Modela | Python 3.14 evidence | Main concern |
|---|---|---|---|---|
| [`langchain-text-splitters`](https://pypi.org/project/langchain-text-splitters/) | Header-scoped Markdown metadata plus recursive separator fallback; length can be supplied by a function | Strong immediate fit for Markdown and explicit section metadata | Package metadata requires Python `>=3.10,<4` | Pulls in LangChain document/core types and is more abstraction than Modela otherwise needs |
| [`semantic-text-splitter`](https://pypi.org/project/semantic-text-splitter/) | CommonMark-aware hierarchy down through block, inline, Unicode sentence, word, grapheme, and character boundaries | Strong lightweight fit; clean string-in/string-out API | Requires Python `>=3.10` and publishes CPython 3.14 wheels | “Semantic” means structure-aware, not embedding-based topic detection; heading lineage may need Modela code |
| [`semchunk`](https://pypi.org/project/semchunk/) | Generic recursive hierarchy from newline/whitespace runs through sentence and clause punctuation to characters; optional Isaacus enrichment-model hierarchy | Strong lightweight fit when exact source offsets and arbitrary token counters are valuable | Requires Python `>=3.10`, classifies Python 3.14, and ships a universal `py3-none-any` wheel | Not Markdown-aware and emits no heading metadata for string input; optional AI mode adds a proprietary API/SDK dependency |
| [`Chunklet-py`](https://pypi.org/project/chunklet-py/) | Constraint-based sentence/section/token packing with percentage overlap and multilingual boundary detection | Plausible direct spike for rich metadata and composable limits | Requires Python `>=3.11`, classifies Python 3.14, and ships a universal wheel | Young, single-maintainer project with a larger mandatory dependency surface and recent breaking V2 API |
| [`ChunkNorris`](https://pypi.org/project/chunknorris/) | Markdown-heading hierarchy with parent headings copied into chunks, balanced newline fallback, and optional hard token cap | Credible Markdown-specific comparison candidate | Requires Python `>=3.10`; its universal wheel was uploaded using CPython 3.14.6, but classifiers name only 3.11 | AGPL-3.0 licensing needs legal approval; output does not document exact source offsets, and small chunks can be discarded |
| [`Chonkie`](https://docs.chonkie.ai/oss/chunkers/overview) | Token, sentence, recursive, table, semantic, neural, and late chunkers behind a common interface | Best experimentation toolkit if several advanced strategies must be benchmarked | Upstream metadata says Python `>=3.10`, but classifiers currently stop at 3.13 ([upstream `pyproject.toml`](https://github.com/chonkie-inc/chonkie/blob/main/pyproject.toml)) | Advanced strategies add dependencies, tuning surface, and sometimes another model/embedding pass; 3.14 must be verified in Modela CI |
| [`LlamaIndex`](https://docs.llamaindex.ai/en/stable/api_reference/node_parsers/semantic_splitter/) | Embedding-derived sentence breakpoints, sentence windows, and recursive parent/child node hierarchies | Strong if Modela also adopts hierarchical retrieval or LlamaIndex nodes | `llama-index-core` requires Python `>=3.10,<4` ([PyPI](https://pypi.org/project/llama-index-core/)) | A retrieval framework is excessive for replacing one splitter; its semantic parser also introduces embedding cost and threshold tuning |
| [`Docling`](https://docling-project.github.io/docling/concepts/chunking/) | Native document hierarchy and metadata; hybrid chunker adds tokenizer-aware split/merge and repeats table headers | Best future choice when Modela owns PDF/DOCX/layout extraction | Docling declares Python `>=3.10,<4` and classifies Python 3.14 ([PyPI](https://pypi.org/project/docling/)) | Current Modela input is already text/Markdown, so conversion/layout dependencies solve a problem outside today's ingestion boundary |

The Python ranges above indicate resolver-level compatibility, not proof that every optional dependency works on Modela's exact Python 3.14 platform. Any candidate must pass a lock/install/import smoke test in the same container and architecture used by CI and production before selection.

### `langchain-text-splitters`

LangChain documents `RecursiveCharacterTextSplitter` as its recommended generic-text splitter. It tries separators in order—by default blank lines, newlines, spaces, then characters—to retain larger related units while satisfying the configured size; overlap is only a target, not a promise at every boundary ([official documentation](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)). `MarkdownHeaderTextSplitter` groups text by configured heading levels, emits header values as metadata, and can retain the heading text with `strip_headers=False` ([official documentation](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter)).

This makes a two-stage pipeline straightforward: split into heading-scoped `Document` objects, then recursively split only oversized sections. The drawback is architectural: the splitter imports `langchain_core.documents.Document` ([upstream source](https://github.com/langchain-ai/langchain/blob/master/libs/text-splitters/langchain_text_splitters/markdown.py)), so Modela should translate immediately into its own chunk value object and prevent LangChain types from escaping the adapter.

### `semantic-text-splitter`

The upstream algorithm selects the highest semantic level that fits, then merges adjacent units without crossing higher-level boundaries. Its Markdown hierarchy understands headings, thematic breaks, blocks (including paragraphs, code blocks, lists, and tables), inline elements, and Unicode text boundaries ([upstream method description](https://github.com/benbrandt/text-splitter#method)). It supports Hugging Face and tiktoken sizing as well as a custom callback ([PyPI usage](https://pypi.org/project/semantic-text-splitter/)).

This aligns well with Modela's minimalist architecture and existing string boundary. It is deterministic and avoids an extra inference request. However, it should not be confused with embedding-based semantic chunking: it preserves syntactic and document-local structure rather than calculating topic similarity.

### Semchunk

Semchunk's default mode is a deterministic recursive splitter rather than an embedding-similarity algorithm. It splits with the most structurally meaningful available delimiter, recursively reduces oversized pieces, and merges undersized neighbors back toward the token budget. Its precedence runs from newline/carriage-return and tab runs through whitespace, sentence terminators, clause separators, sentence interrupters, word joiners, and finally arbitrary characters ([upstream algorithm description](https://github.com/isaacus-dev/semchunk#how-it-works-)). This is more context-preserving than Modela's current raw slicing, but it is generic text structure: it does not parse Markdown headings, fenced code blocks, lists, or tables as CommonMark nodes.

The API is unusually flexible for Modela's multi-provider setup. `chunkerify()` accepts an OpenAI model name, tiktoken encoding name, Hugging Face model name, any tokenizer exposing `encode()`, or an arbitrary `str -> int` token counter; `chunk()` accepts the counter directly. It memoizes counts by default, can process a sequence of documents using multiple processes, and returns optional `(start, end)` character spans that satisfy `chunk == text[start:end]` ([upstream API documentation](https://github.com/isaacus-dev/semchunk#chunkerify)). Overlap may be a fraction of chunk size or an absolute token count; the implementation first produces smaller semantic units and then merges sliding groups, so overlap follows semantic boundaries rather than blindly slicing a token window ([upstream overlap algorithm](https://github.com/isaacus-dev/semchunk#how-it-works-)). The public API documents synchronous batching and multiprocessing, not an asynchronous chunking interface.

The core package is MIT-licensed, requires Python `>=3.10`, explicitly classifies Python 3.14, and publishes a platform-independent wheel. Its only unconditional runtime dependency is `tqdm`; `dill` is Windows-only, while tiktoken and Transformers remain optional ([PyPI metadata and files](https://pypi.org/project/semchunk/), [upstream `pyproject.toml`](https://github.com/isaacus-dev/semchunk/blob/main/pyproject.toml)). Those are strong compatibility signals, though Modela should still run a Python 3.14 lock/import test with the chosen tokenizer.

For plain-string input, the output carries content and optional offsets but no heading path, block type, token count, or other document metadata. Modela would need to derive and attach those fields itself. Semchunk 4.x also offers an optional AI mode that uses Isaacus enrichment models to create a hierarchy of extracted spans before packing them into chunks; this requires the separate Isaacus SDK, an API key, and a network call ([upstream AI-mode documentation](https://github.com/isaacus-dev/semchunk#quickstart-)). The maintainer-published Legal RAG QA benchmark reports gains over LangChain recursive and Chonkie on that one legal dataset, but it is vendor-run and domain-specific, so it is evidence to reproduce on Modela's corpus—not a selection result ([upstream benchmark](https://github.com/isaacus-dev/semchunk#benchmarks-)).

### Chonkie

Chonkie's appeal is breadth. Its official overview exposes recursive, sentence, table, semantic, late, neural, and other strategies under a common API ([official overview](https://docs.chonkie.ai/oss/chunkers/overview)). Its `SemanticChunker` groups sentence spans using embedding similarity, has a maximum token size, and exposes similarity windows, thresholding, filtering, and skip-window merging ([official semantic chunker documentation](https://docs.chonkie.ai/oss/chunkers/semantic-chunker)). Optional extras isolate semantic and provider dependencies ([PyPI](https://pypi.org/project/chonkie/)).

That makes it useful for a research branch, particularly to compare deterministic recursive and embedding-semantic strategies with consistent result objects. It is not the safest first production dependency on Python 3.14 until its optional tokenizer/model stack is verified, and its richer tuning surface increases operational and evaluation work.

### LlamaIndex

`SemanticSplitterNodeParser` embeds neighboring sentence groups and creates breakpoints where cosine dissimilarity exceeds a percentile threshold ([official API/source documentation](https://docs.llamaindex.ai/en/stable/api_reference/node_parsers/semantic_splitter/)). `HierarchicalNodeParser` produces overlapping parent/child levels such as 2,048, 512, and 128 tokens ([official API/source documentation](https://docs.llamaindex.ai/en/stable/api_reference/node_parsers/hierarchical/)).

These are valuable patterns, especially “retrieve small, return larger context,” but adopting LlamaIndex solely for chunk production would introduce its node and embedding abstractions alongside Modela's existing adapters and pgvector model. Modela can implement the parent/child pattern directly later if evaluation proves it useful.

### Docling

Docling's `HierarchicalChunker` operates on a `DoclingDocument` and attaches structural metadata such as headings and captions. Its `HybridChunker` refines those structural chunks to a tokenizer limit, splits only oversized chunks, and merges undersized peers sharing headings/captions; table chunks can repeat headers ([official chunking documentation](https://docling-project.github.io/docling/concepts/chunking/)). It also separates a chunk's original text from `contextualize(chunk)`, the metadata-enriched string intended for embedding ([official hybrid example](https://docling-project.github.io/docling/_generated/examples/hybrid_chunking/)).

That distinction is directly useful to Modela's design. The library itself should be deferred until ingestion accepts source files or structured extraction results. Running already-extracted Markdown back through a full document-conversion stack adds complexity without recovering layout information that was already lost.

## Other relevant alternatives

The ecosystem contains several credible tools adjacent to Semchunk. Chunklet-py and ChunkNorris are close enough to join the main comparison table for Modela's current Markdown input. The others are better treated as future ingestion components or experimental boundary detectors rather than general-purpose chunkers.

### Chunklet-py

Chunklet-py's `DocumentChunker` combines configurable sentence, token, and Markdown section-break constraints with percentage overlap. It accepts a pluggable token counter, supports multilingual sentence segmentation and malformed unbroken-text fallbacks, and returns chunk objects whose metadata includes source references, spans, and document structure ([upstream README and API examples](https://github.com/speedyk-005/chunklet-py#the-constraint-based-logic)). On paper, that is the closest additional package to Modela's proposed `ChunkDraft` contract and merits a small corpus spike.

The tradeoff is maturity and weight. It is a young, single-maintainer project whose V2 release changed its public API, and the base install includes several sentence-boundary/language packages, multiprocessing, Pydantic, Typer, and other utilities; document-format processors add another optional dependency set ([upstream package definition](https://github.com/speedyk-005/chunklet-py/blob/main/pyproject.toml)). It requires Python `>=3.11`, explicitly classifies Python 3.14, and ships a universal wheel ([PyPI metadata](https://pypi.org/project/chunklet-py/)). Before treating it as a finalist, verify that its spans remain exact under overlap/continuation markers, that Markdown heading lineage is sufficient for contextualization, and that the dependency footprint is acceptable.

### ChunkNorris

ChunkNorris is an actively released Markdown-oriented parser/chunker. `MarkdownChunker` recursively uses heading levels to keep sections homogeneous, prepends parent headings for context, aims for similarly sized chunks, and balances oversized chunks around newline boundaries. Its primary sizing controls are soft and hard **word** counts; a supplied tokenizer with an `encode()` method can enforce a final hard token ceiling ([upstream README and configuration](https://github.com/wikit-ai/chunknorris#how-it-works)). This is close to Modela's proposed title/heading contextualization and makes it a worthwhile output-quality comparison against the three primary candidates.

The fit is not complete. The documented result API exposes rendered chunk text rather than exact source character spans or a general metadata contract, and `min_chunk_word_count` discards undersized chunks rather than merging or retaining them. Its distribution bundles Markdown, HTML, and PDF parsing concerns that Modela does not currently need. Most importantly, it is licensed AGPL-3.0, so Modela should not add it as a production dependency without a license review ([upstream package metadata](https://github.com/wikit-ai/chunknorris/blob/main/pyproject.toml)). The package requires Python `>=3.10`, ships a universal wheel, and the current wheel was uploaded from CPython 3.14.6; that is encouraging packaging evidence, not a substitute for an install/import test with all transitive dependencies ([PyPI release metadata](https://pypi.org/project/chunknorris/)).

### Unstructured

Unstructured chunks typed elements produced by its document partitioners instead of re-discovering structure from a flat string. `basic` packs whole elements until a hard/soft limit; `by_title` additionally closes chunks on detected section titles and metadata/page boundaries. It can retain the original elements in `metadata.orig_elements`, isolate and split tables, repeat table headers, and now supports token limits through named tiktoken model/encoding values ([official chunking documentation](https://docs.unstructured.io/open-source/core-functionality/chunking), [upstream `chunk_by_title` API](https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/chunking/title.py)). That is a meaningful layout-aware alternative when Modela ingests PDFs or office files and still has element provenance available.

It is not a Semchunk-like replacement at today's plain Markdown boundary: the value comes from Unstructured's partitioned element model, its dependency surface includes document-processing concerns, and its chunks preserve source elements rather than documenting exact flat-string offsets. The current release explicitly requires Python `>=3.11,<3.14`, so it cannot be installed in Modela's Python 3.14 environment ([PyPI metadata](https://pypi.org/project/unstructured/)). Keep it alongside Docling as a future source-file ingestion option, not in the near-term splitter spike.

### Segment Any Text (`wtpsplit`)

`wtpsplit` supplies the learned Segment Any Text (SaT) sentence/semantic-unit boundary detector across 85 languages. With length constraints, its Viterbi mode chooses globally optimal boundaries by balancing the model's boundary probabilities against minimum, maximum, and preferred **character-length** priors; concatenating the returned segments reconstructs the source exactly ([upstream README](https://github.com/segment-any-text/wtpsplit#length-constrained-sentence-segmentation-new)). This could improve the sentence layer inside a Modela-owned hierarchical chunker for noisy OCR, punctuation-free text, or multilingual content where regular expressions and conventional sentence tokenizers fail.

SaT is a segmentation primitive, not a full RAG chunker: it has no embedding-token budget, overlap policy, heading awareness, or documented chunk metadata/offset objects. Source offsets can be derived cumulatively only while exact reconstruction is enabled. The base install pulls in Transformers, Hugging Face Hub, NumPy, scikit-learn, pandas, MosesTokenizer, and related packages; ONNX is optional ([upstream package definition](https://github.com/segment-any-text/wtpsplit/blob/main/setup.py)). It requires Python `>=3.9` and ships a universal wheel, but neither its classifiers nor release build prove that the ML dependency stack works on Python 3.14 ([PyPI metadata](https://pypi.org/project/wtpsplit/)). Evaluate it only if baseline tests expose sentence-boundary failures worth the model/runtime cost.

### Chonky

Chonky is a focused neural paragraph/topic splitter rather than an embedding-similarity chunker. Its `ParagraphSplitter` downloads a fine-tuned Transformer boundary model; upstream publishes English and multilingual models from 66M to 396M parameters and reports boundary-detection benchmarks against SaT and several RAG splitters ([upstream README](https://github.com/mirth/chonky)). This makes it a credible research comparator for learned topic boundaries.

It is a poor first production fit for Modela. Upstream tells callers to strip Markdown/XML/HTML before splitting, which throws away the heading structure Modela wants to preserve. The public API returns strings and does not document offsets, metadata, overlap, or a configurable embedding-token ceiling. The package requires Python `>=3.9` and has a universal wheel, but its Transformers/PyTorch model stack still needs an explicit Python 3.14 test ([PyPI metadata](https://pypi.org/project/chonky/)). It also adds local model download, memory, latency, and model-version reproducibility concerns.

### Tools not promoted to the shortlist

Sentence tokenizers in spaCy, Stanza, NLTK, and syntok can be useful implementation primitives, but they do not pack sentences into tokenizer-bounded, overlapping, structure-aware RAG chunks. Haystack and similar RAG frameworks expose capable splitters, but adopting another framework solely for a generic splitter would duplicate Modela's orchestration. The `semantic-chunker` package is also not a distinct contender here: its core dependency is the already-reviewed `semantic-text-splitter`. These are therefore omitted from the comparison table rather than inflating the shortlist with wrappers and adjacent NLP utilities.

## Recommended target architecture

Keep orchestration in Modela and make the library replaceable:

```text
raw_content
  -> frontmatter/body split
  -> content snapshot (hash/version)
  -> ChunkingStrategy.chunk(document context, body, config)
       -> heading-scoped sections
       -> structure-aware token-limited chunks
       -> small-tail merge / section-local overlap
       -> ChunkDraft[]
  -> contextualize each ChunkDraft for embedding
  -> bounded embedding batches
  -> atomic replace only if content snapshot is still current
  -> retrieve raw body + metadata; optionally expand neighbors/parent
```

The Modela-owned contract should return more than strings:

```python
@dataclass(frozen=True)
class ChunkDraft:
    content: str                 # exact source excerpt returned to callers
    embedding_content: str       # title/heading-enriched representation
    heading_path: tuple[str, ...]
    start_offset: int
    end_offset: int
    token_count: int
```

The first strategy, `markdown_recursive_v1`, should:

1. Split at Markdown headings and retain a heading breadcrumb.
2. Keep blocks, paragraphs, sentences, and words intact in that order where possible.
3. Enforce size with an explicitly configured tokenizer/encoding, ideally aligned with the embedding model.
4. Start with a 512-token target and a small, section-local overlap (for example 50–75 tokens), then tune from evaluation. Never overlap across heading boundaries.
5. Merge very small trailing chunks when doing so stays inside the token budget and the same heading scope.
6. Preserve long code blocks/tables as coherent units when they fit; define a deterministic row/line fallback when they do not.
7. Form embedding input such as `Document: {title}\nSection: {heading breadcrumb}\n\n{content}` while returning/storing the exact source excerpt separately.

Do not hard-code “tokens” without recording which tokenizer produced the count. Modela's embedding adapter currently does not expose tokenization, and provider model IDs do not always map to a locally available tokenizer. The configuration therefore needs `size_unit`, `tokenizer` or `encoding`, and a deliberate fallback policy. A character fallback may remain valid, but must be named and measured rather than silently substituted.

## Schema and API changes

Extend `knowledge_chunks` with enough provenance to reproduce and inspect results:

| Field | Purpose |
|---|---|
| `heading_path` (`JSONB`) | Section lineage used for contextualization and display |
| `start_offset`, `end_offset` | Exact character span in `KnowledgeDocument.content` |
| `token_count` | Observability and budget validation |
| `content_hash` | Stable deduplication/debugging key for the raw excerpt |
| `embedding_content` or `context_prefix` | Audit what was embedded without reconstructing it from mutable title/metadata |
| `parent_chunk_id` (nullable, later) | Enables small-to-big retrieval without adopting a retrieval framework |
| `index_generation` or `source_content_hash` | Prevents a stale async task from replacing a newer index |

Keep `chunk_params`, but expand its snapshot to include strategy version, size unit, tokenizer/encoding, overlap policy, contextualization template version, and library/version. Strategy names should be versioned (`markdown_recursive_v1`) so a code change cannot silently create non-reproducible chunks under the same config.

Retrieval should eventually return a structured result containing content, document ID/title, heading path, offsets, and score rather than `list[str]`. This enables citations, debugging, neighbor expansion, and evaluation without changing vector ranking semantics.

## Staged adoption

### Stage 0 — establish a baseline

- Fix the fully duplicated trailing-chunk edge case in `fixed_size`.
- Capture a representative corpus and 30–100 real or reviewed question/relevant-span pairs.
- Record current chunk counts, embedding tokens/cost, indexing latency, retrieval metrics, and qualitative boundary failures.

### Stage 1 — deterministic structure-aware strategy

- Add the Modela-owned `ChunkDraft` and strategy protocol.
- Spike `langchain-text-splitters`, `semantic-text-splitter`, and Semchunk's non-AI mode against the corpus and Python 3.14 deployment image.
- Ship `markdown_recursive_v1` behind configuration while retaining `fixed_size` for rollback.
- Store heading paths, offsets, token counts, hashes, and strategy/version metadata.
- Batch provider embedding calls by count and token budget.

### Stage 2 — contextualized retrieval

- Embed title + heading breadcrumb + body, while returning the unmodified body and metadata.
- Add optional adjacent-chunk expansion within the same document/section.
- Re-evaluate and tune token size and overlap; do not assume 512/64 wins universally.

### Stage 3 — advanced experiments only if justified

- Benchmark Chonkie or LlamaIndex-style embedding-semantic boundaries against the deterministic strategy.
- Test parent/child (“small-to-big”) retrieval if questions need precise matching but answers require wider context.
- Introduce Docling only when Modela ingests PDFs, DOCX, presentations, or a structured `DoclingDocument` representation.

## Evaluation criteria

Library selection and chunk parameters should be decided by the same end-to-end corpus, not by visual inspection alone.

### Retrieval quality

- **Recall@k / hit rate@k:** whether at least one chunk containing the reviewed relevant span appears in the first `k` results.
- **MRR or nDCG@k:** how early and how consistently relevant chunks rank.
- **Context precision:** proportion of retrieved tokens that are relevant rather than neighboring noise.
- **Boundary integrity:** reviewed rate of split sentences, orphan headings, broken lists/tables/code blocks, and mixed-topic chunks.
- **Answer support:** on a fixed answer-generation model, whether the answer is correct and every material claim is supported by retrieved text.

### Efficiency and operations

- Chunks and embedded tokens per document, duplicated-token ratio, and vector-storage growth.
- Chunking CPU time and peak memory at typical, p95, and 1 MiB inputs.
- Embedding requests, indexing latency, provider cost, and failure/retry rates.
- Determinism across repeated runs and stability after library upgrades.
- Python 3.14 lock/install success and supported wheels for production platforms.
- Correct behavior for empty input, one oversized sentence/block, multilingual text, malformed Markdown, tables, code fences, huge unbroken strings, and the 1,000-chunk limit.

The acceptance bar should be explicit before rollout—for example: improve recall@5 materially without regressing answer support, keep indexing cost within an agreed bound, produce no chunks over the embedding model's input limit, and eliminate fully redundant chunks. Exact thresholds need baseline measurements from Modela's corpus.

## Risks and mitigations

- **Tokenization mismatch:** a generic encoding can undercount another provider's input. Record the tokenizer and validate actual provider limits; fail clearly when no safe mapping exists.
- **Dependency compatibility on Python 3.14:** declared version ranges do not guarantee optional native/ML dependencies. Test resolution and imports in the production image and pin the selected versions.
- **Embedding-semantic cost and instability:** semantic breakpoint approaches add embedding/model work and threshold sensitivity. Keep them experimental until they outperform deterministic chunking end to end.
- **Context-prefix dominance:** repeated title/headings can distort very short chunks. Cap prefix length, measure raw-body versus contextualized embeddings, and merge tiny chunks.
- **Markdown parser differences:** malformed or generated Markdown may produce surprising structure. Maintain adversarial fixtures and a deterministic plain-text fallback.
- **Index races:** asynchronous tasks may finish out of order. Compare the source hash/generation before replacement and discard stale results.
- **Migration/reindex cost:** new metadata and embedding input require a full reindex. Roll out by strategy/config generation, retain the prior usable index until replacement succeeds, and monitor failures.
- **Framework leakage:** LangChain/LlamaIndex types can spread into persistence and retrieval. Confine third-party objects to adapters returning Modela-owned `ChunkDraft` values.

## Techniques considered and deferred

Two chunking/embedding *techniques*—distinct from any library choice above—came up in a later review and are worth naming explicitly so the record shows they were considered rather than overlooked:

- **Anthropic's Contextual Retrieval.** An LLM call generates a bespoke ~50–100 token context blurb per chunk before embedding, rather than a static heading breadcrumb; published results report meaningful precision gains, in some cases combined with reranking. Stage 2 of this document's staged adoption plan (`## Staged adoption`) only proposes the free, no-LLM-call variant—embedding a static title/heading breadcrumb. That is a deliberate cost/latency tradeoff, not an oversight: an LLM call per chunk at index time adds cost and latency to every reindex. Revisit only if Stage 2's evaluation shows the static breadcrumb is insufficient.
- **Late chunking (embed-then-pool).** Embed the full document first, then pool token-level embeddings per chunk, instead of chunking text and embedding each chunk independently. This does not fit the `ChunkingStrategy.chunk(...) -> ChunkDraft[]` seam this document proposes—it changes the embedding call shape from batched per-chunk calls to one document-level call—so it cannot be slotted in as a Stage 3 checkbox alongside Chonkie/LlamaIndex-style experiments. If pursued, it needs its own architectural note covering how it interacts with Modela's per-chunk embedding-config and provider-adapter model.

## Decision recommendation

Proceed with a short implementation spike for `markdown_recursive_v1`, comparing:

1. `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` with a token length function; and
2. `semantic_text_splitter.MarkdownSplitter` plus Modela-owned heading-path extraction; and
3. Semchunk's non-AI chunker plus Modela-owned Markdown heading scoping and metadata attachment; and
4. Chunklet-py's `DocumentChunker` as a secondary candidate if its span fidelity and dependency footprint pass an initial smoke test.

Choose from measured retrieval quality, boundary integrity, offset fidelity, Python 3.14 installability, and dependency footprint. **With dependency footprint as the deciding priority, the expected default is `semantic_text_splitter.MarkdownSplitter` plus Modela-owned heading-path extraction**, since it is comparably light to `semchunk` but CommonMark-aware, and the heading-path extraction cost is the same for both. Fall back to the LangChain pair only if the spike shows its built-in heading metadata is materially more reliable than a Modela-owned extractor and the added abstraction/dependency weight is acceptable; fall back to Semchunk only if exact offsets or arbitrary-tokenizer support prove decisive in the corpus evaluation. Chunklet-py is the strongest additional direct alternative, but its exact span behavior, dependencies, and project maturity need closer validation. ChunkNorris is a useful Markdown-specific comparison or source of design ideas, but should enter the dependency shortlist only after AGPL review. Keep Semchunk's AI mode, Chonkie, SaT, and Chonky as advanced-strategy experiments; LlamaIndex as a source of hierarchical retrieval patterns rather than a near-term dependency; and Docling or Unstructured as future structured-file ingestion layers.

Two searches for newer entrants (September 2026) turned up `markdown_hero` and `rag-chunk`, both narrower and without the maturity signals (PyPI adoption, Python 3.14 evidence, license clarity) required of the finalists above—not recommended for the shortlist, and not worth a spike slot.
