# Document Summarization

Modela exposes two endpoints for summarizing documents:

- `POST /summarize/text` — summarize a plain text string
- `POST /summarize/file` — summarize a document at a URL (S3 presigned URLs, public URLs, etc.)

Both endpoints resolve a `ModelConfig` by slug, or fall back to the default config of type `summary` when no slug is provided.

---

## 1. Create a default summary ModelConfig

Before calling either endpoint without an explicit `model` slug, create a `ModelConfig` with `config_type: "summary"` and `is_default: true`.

```http
POST /model-configs
Content-Type: application/json

{
  "slug": "claude-summary",
  "name": "Claude Summarizer",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "config_type": "summary",
  "is_default": true
}
```

Only one default per `config_type` is enforced at the DB level. Creating a new default automatically clears the previous one within the same type, so chat and generation defaults are not affected.

Make sure `ANTHROPIC_API_KEY` is set in your environment when using the `anthropic` provider. For OpenAI, use `OPENAI_API_KEY`.

---

## 2. Summarize text

```http
POST /summarize/text
Content-Type: application/json
Authorization: Bearer <token>

{
  "content": "The board approved a $2M budget increase for Q3..."
}
```

Pass an explicit `model` slug to override the default:

```http
POST /summarize/text
Content-Type: application/json
Authorization: Bearer <token>

{
  "content": "The board approved a $2M budget increase for Q3...",
  "model": "gpt4o-summary"
}
```

**Response**

```json
{
  "summary": "The board approved a budget increase of $2M for Q3.",
  "model": "claude-summary",
  "request_id": "a1b2c3d4-..."
}
```

---

## 3. Summarize a file URL

```http
POST /summarize/file
Content-Type: application/json
Authorization: Bearer <token>

{
  "file_url": "https://vaulta.s3.amazonaws.com/47ca82aa-...?AWSAccessKeyId=...&Signature=...&Expires=..."
}
```

S3 presigned URLs have no file extension, so Modela defaults to `application/pdf`. Pass `mime_type` explicitly for other formats:

```http
POST /summarize/file
Content-Type: application/json
Authorization: Bearer <token>

{
  "file_url": "https://example.com/report",
  "mime_type": "text/plain"
}
```

Anthropic receives the URL directly. For providers that don't support URL inputs natively (e.g. OpenAI), pydantic-ai downloads the file and passes it as binary content.

---

## 4. Custom summarization prompt

By default, Modela instructs the model to *"Summarize the following document concisely."* To customize this, attach a `SystemPrompt` to the `ModelConfig`.

**Generic bullet-point summary** — a good starting point for most use cases:

```http
POST /system-prompts
{
  "name": "generic-summary-prompt",
  "content": "Summarize the following document in a few concise sentences. Focus on the main ideas and omit unnecessary detail. Return only the summary text — no headings, bullet points, labels, or preamble."
}

→ { "id": "prompt-uuid", ... }

POST /model-configs
{
  "slug": "claude-summary",
  "name": "Claude Summarizer",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "config_type": "summary",
  "system_prompt_id": "prompt-uuid",
  "is_default": true
}
```

**Specialized prompt** — for executive/decision-focused summaries:

```http
POST /system-prompts
{
  "name": "detailed-summary-prompt",
  "content": "Provide a detailed executive summary with key decisions and action items."
}
```

Then call the endpoint with that config's slug:

```http
POST /summarize/text
{
  "content": "...",
  "model": "detailed-summarizer"
}
```

---

## Error reference

| Status | Cause |
|--------|-------|
| `422` | `content` missing from `/summarize/text`, or `file_url` missing from `/summarize/file` |
| `404` | Explicit `model` slug not found, or no default `summary` config configured |
| `502` | Provider error (model unavailable, unsupported file type, etc.) |
| `504` | Provider timeout |
