## Problem Statement

Operators need a dedicated endpoint to summarize documents using any configured AI provider. Currently, the `/chat/completions` endpoint is the only way to interact with models, and callers must construct their own prompting, message history, and model selection logic to summarize documents. There is no standardized way to submit a document — either as raw text or as a file URL (e.g. an S3 presigned URL) — and receive a concise summary. Additionally, `ModelConfig` has no concept of purpose or type, so there is no way to designate a config as the "default for summarization" separately from the "default for chat."

## Solution

Add a `config_type` field to `ModelConfig` to allow operators to designate configs for specific use cases (`chat`, `summary`, `generation`). Add two endpoints — `POST /summarize/text` for raw text and `POST /summarize/file` for file URLs — each with an unambiguous, purpose-specific request shape. Both resolve the appropriate `ModelConfig` (by explicit slug or by the default `summary`-typed config) and return a concise summary string. File URL ingestion is handled transparently via pydantic-ai's `DocumentUrl`, which forwards the URL to providers that support it natively (e.g. Anthropic) and downloads and converts the file for those that do not.

## User Stories

1. As an API consumer, I want to POST a raw text string to `/summarize/text` and receive a concise summary, so that I can summarize content without building my own prompting logic.
2. As an API consumer, I want to POST a file URL to `/summarize/file` and receive a summary, so that I can summarize documents stored in object storage without downloading them first.
3. As an API consumer, I want to pass an optional `mime_type` to `/summarize/file`, so that the correct document format is used when the URL has no file extension (e.g. S3 presigned URLs).
4. As an API consumer, I want `mime_type` to default to `application/pdf` when omitted from `/summarize/file`, so that the common case (PDF documents) works without extra configuration.
5. As an API consumer, I want to pass an optional `model` slug to either summarize endpoint to select a specific `ModelConfig`, so that I can use a non-default model for specific summarization tasks.
6. As an API consumer, I want both summarize endpoints to fall back to the default `summary`-typed `ModelConfig` when no `model` slug is provided, so that I don't need to pass a config on every request.
7. As an API consumer, I want the summary response to include the `model` slug that was used, so that I can audit which config processed my request.
8. As an API consumer, I want the summary response to include a `request_id`, so that I can correlate it with logs or usage records.
9. As an API consumer, I want `/summarize/text` to only accept a `content` string — no file fields — so that the endpoint contract is unambiguous and self-documenting.
10. As an API consumer, I want `/summarize/file` to only accept a `file_url` — no raw text field — so that the endpoint contract is unambiguous and self-documenting.
11. As an operator, I want to assign a `config_type` of `summary`, `chat`, or `generation` to a `ModelConfig`, so that different endpoint types can each have their own default config.
12. As an operator, I want setting `is_default: true` on a `summary`-typed config to clear the previous default only within the `summary` type, so that chat and generation defaults are not affected.
13. As an operator, I want the system prompt linked to a `summary` `ModelConfig` to be used as the summarization instruction, so that I can customize summarization behavior per config.
14. As an operator, I want both summarize endpoints to use a sensible built-in prompt ("Summarize the following document concisely.") when the resolved `ModelConfig` has no linked system prompt, so that summarization works out-of-the-box.
15. As an operator, I want Anthropic-provisioned configs to pass file URLs directly to the provider, so that large PDFs are not unnecessarily downloaded by the gateway.
16. As an operator, I want OpenAI-provisioned configs that receive a file URL to have the file downloaded and passed as binary content, so that summarization works even when the provider does not support native URL inputs.
17. As a developer, I want a clear validation error when `content` is missing from `/summarize/text`, so that misconfigured clients get a meaningful message.
18. As a developer, I want a clear validation error when `file_url` is missing from `/summarize/file`, so that misconfigured clients get a meaningful message.
19. As a developer, I want a clear error when the resolved `ModelConfig` uses a provider that does not support the given document type, so that the failure is traceable.
20. As a developer, I want both summarize commands to log usage (tokens in/out) the same way the completion command does, so that usage attribution works uniformly across endpoint types.

## Implementation Decisions

### Schema changes

- Add a `config_type` enum column to `model_configs` with values: `chat`, `summary`, `generation`. Nullable with no default to preserve backward compatibility for existing rows; existing records default to `chat` via a migration data backfill.
- Add a partial unique index on `(config_type)` where `is_default = true` and `deleted_at IS NULL`, enforcing at most one active default per type at the DB level.
- The `_clear_default` logic in `ModelConfigRepository` must be scoped to the same `config_type` as the record being set to default.
- Add a new `get_default_for_type(config_type)` method to `ModelConfigRepository`.

### New modules

- **Summarize schemas** — two request models: `SummarizeTextRequest` (`content: str`, `model: str | None`) and `SummarizeFileRequest` (`file_url: str`, `mime_type: str = "application/pdf"`, `model: str | None`); shared response model `SummarizeResponse` (`summary: str`, `model: str`, `request_id: str`).
- **CreateSummarizeCommand** — accepts a union input (`str` content or `DocumentUrl`); resolves `ModelConfig` by slug or by `get_default_for_type("summary")`; resolves optional system prompt (falls back to built-in default); builds a `UserPromptPart` with either `TextContent` or `DocumentUrl`; runs a pydantic-ai `Agent` with `result_type=str`; logs usage; returns a `SummarizeResponse`. Both routers delegate to this single command.
- **Summarize router** — `POST /summarize/text` and `POST /summarize/file`, both RBAC-guarded (same `completion` resource), inject `project_id`, `db`, `current_user`; each constructs the appropriate input and delegates to `CreateSummarizeCommand`.

### Modified modules

- `ModelConfig` ORM model — add `config_type` column (SQLAlchemy `String` or `Enum`).
- `ModelConfigBase` / `ModelConfigCreate` / `ModelConfigUpdate` / `ModelConfigResponse` schemas — add `config_type` field.
- `ModelConfigRepository` — add `get_default_for_type`, scope `_clear_default` to `config_type`.
- `app/main.py` — register summarize router.

### API contract

```
POST /summarize/text
Authorization: Bearer <token>
X-Project-Id: <project_id>

{
  "content": "Long text...",         // required
  "model": "my-summary-config"       // optional; falls back to default summary config
}

POST /summarize/file
Authorization: Bearer <token>
X-Project-Id: <project_id>

{
  "file_url": "https://...",         // required
  "mime_type": "application/pdf",    // optional; defaults to application/pdf
  "model": "my-summary-config"       // optional; falls back to default summary config
}

→ 200 (both endpoints)
{
  "summary": "...",
  "model": "my-summary-config",
  "request_id": "..."
}
```

- `422` (FastAPI validation) if `content` is missing from `/summarize/text` or `file_url` is missing from `/summarize/file`.
- `404` if an explicit `model` slug is not found, or if no explicit model is given and no default `summary` config exists.
- `502` / `504` for provider errors, same as the completion endpoint.

### Document ingestion

- For `file_url` inputs, wrap the URL in pydantic-ai's `DocumentUrl(url, media_type=mime_type)` and include it as content in `UserPromptPart`.
- `force_download` is left at the default (`False`): pydantic-ai forwards the URL to providers that support it natively and downloads transparently for those that don't.

## Testing Decisions

A good test in this codebase exercises the full request-response path through the router (not just a unit of internal logic), uses the real test database with transaction rollback, and asserts on the HTTP response rather than internal state. Tests should not mock the database or the command layer — only the AI provider call.

Modules to test:
- **`/summarize/text` router** — happy path with `content`, with explicit `model` slug, missing `content` (expect 422), unknown model slug (expect 404), no default summary config (expect 404). Prior art: `tests/routers/test_completion_router.py`.
- **`/summarize/file` router** — happy path with `file_url`, with explicit `mime_type`, with explicit `model` slug, missing `file_url` (expect 422), unknown model slug (expect 404), no default summary config (expect 404).
- **CreateSummarizeCommand** — config resolution (slug lookup, default-for-type lookup, fallback system prompt logic). Both text and file input paths should be exercised. Prior art: `tests/commands/test_create_completion_command.py` (if it exists).
- **ModelConfigRepository** — `get_default_for_type` returns the correct config; `_clear_default` scoped to type does not touch other types' defaults.

## Out of Scope

- Streaming summarization responses.
- Summarizing multiple documents in a single request.
- Returning structured/JSON summaries (the output is always a plain string).
- Session/history tracking for summarization requests.
- File type detection beyond the caller-supplied `mime_type` (no magic-byte sniffing).
- Enforcing that OpenAI configs reject non-image file inputs at the routing layer (errors bubble up from the provider).

## Further Notes

- The `config_type` column does not restrict which endpoint a config can be used with. Callers may pass any config slug to either summarize endpoint regardless of its `config_type`; the type only affects which config is resolved when no slug is provided.
- pydantic-ai's SSRF protection (`force_download=False`) blocks private IPs and cloud metadata endpoints. S3 presigned URLs on public internet IPs are unaffected.
- If a future provider adapter does not support `DocumentUrl`, the failure will surface as a pydantic-ai `UnexpectedModelBehavior` exception, which the command should catch and re-raise as a `ProviderError`.
