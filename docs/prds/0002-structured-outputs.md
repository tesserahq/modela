# PRD 0002 — Structured Outputs

## Overview

This phase adds structured output support: the ability to request a JSON response conforming to a specific schema, validated by Modela before returning to the caller. The schema can be defined on the **ModelConfig** (authoritative, always enforced) or supplied ad-hoc in the request (used only when the ModelConfig has no `output_schema`).

---

## Goals

- Allow callers to receive validated, schema-conforming JSON responses from any LLM
- Enforce `output_schema` from ModelConfig when present
- Accept `output_schema` in the request body as a fallback when ModelConfig has none
- Return a structured validation error if the provider response does not conform
- Inject the schema into the provider request using the appropriate provider mechanism

---

## Non-Goals

- Per-request override when ModelConfig already defines an `output_schema` (config is authoritative)
- Automatic schema generation from Python type annotations (caller-side concern)
- Coercing or auto-correcting non-conforming responses (fail fast, don't guess)
- Multi-provider structured output (covered in PRD 0003 for each new provider)

---

## Background

Structured outputs remove the need for callers to parse or validate LLM responses themselves. Modela becomes the single enforcement point: inject the schema into the provider request, receive the response, validate it, and return clean JSON or a clear error.

The schema definition introduced on `ModelConfig.output_schema` in PRD 0001 was stored but not enforced. This PRD activates it.

**Resolution order:**

1. If `ModelConfig.output_schema` is set → use it (authoritative, request-level schema ignored)
2. Else if request body contains `output_schema` → use it
3. Else → no structured output, return free-form text as normal

---

## Schema Format

Schemas are expressed as **JSON Schema (Draft 7)** objects. Callers may also submit a simplified form (a flat object with field names and types), but internally Modela normalises everything to JSON Schema before use.

Example:

```json
{
  "type": "object",
  "properties": {
    "sentiment": {
      "type": "string",
      "enum": ["positive", "negative", "neutral"]
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "topics": { "type": "array", "items": { "type": "string" } }
  },
  "required": ["sentiment", "confidence"]
}
```

---

## API Changes

### `POST /chat/completions` — updated request body

```json
{
  "model": "openai-gpt-4o",
  "messages": [{ "role": "user", "content": "Analyse the review." }],
  "output_schema": {
    "type": "object",
    "properties": {
      "sentiment": {
        "type": "string",
        "enum": ["positive", "negative", "neutral"]
      },
      "confidence": { "type": "number" }
    },
    "required": ["sentiment", "confidence"]
  }
}
```

`output_schema` is ignored if `ModelConfig.output_schema` is already set.

### Response — structured output

When a schema is active, the response `content` is a parsed JSON object:

```json
{
  "id": "chatcmpl-...",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": {
        "sentiment": "positive",
        "confidence": 0.91
      }
    },
    "finish_reason": "stop"
  }],
  ...
}
```

### Errors

| Code  | Condition                                              |
| ----- | ------------------------------------------------------ |
| `422` | `output_schema` in request is not valid JSON Schema    |
| `502` | Provider returned output that failed schema validation |

The `502` body includes a `validation_errors` field with the JSON Schema validation failures, so callers can debug prompt/schema mismatches.

```json
{
  "error": "StructuredOutputValidationError",
  "message": "Provider response did not conform to the requested schema.",
  "validation_errors": [
    {
      "path": "$.confidence",
      "message": "Value 'high' is not of type 'number'"
    }
  ],
  "raw_content": "{ \"sentiment\": \"positive\", \"confidence\": \"high\" }"
}
```

---

## Implementation

### OpenAI Provider Injection

OpenAI supports structured outputs via `response_format`:

```python
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "modela_output",
        "strict": True,
        "schema": output_schema,
    }
}
```

This is merged into the request before forwarding. The `extra_body` field (PRD 0001) still applies on top.

### Validation

After receiving the provider response:

1. Parse `choices[0].message.content` as JSON
2. Validate against the resolved schema using `jsonschema` (Python library)
3. On success: replace the string content with the parsed dict in the response
4. On failure: raise `StructuredOutputValidationError` → return `502` with validation details

### ModelConfig admin update

The `output_schema` field on ModelConfig (introduced in PRD 0001) is now actively enforced. The CRUD API already supports reading/writing it. No schema changes required.

---

## Dependencies

- PRD 0001 (foundation, ModelConfig, OpenAI adapter)
- `jsonschema` Python library (new dependency)

---

## Success Criteria

- Request with `output_schema` returns a validated JSON object in `content`
- ModelConfig `output_schema` takes precedence over request-level schema
- Invalid schema in request body returns `422` before hitting the provider
- Non-conforming provider response returns `502` with `validation_errors`
- Free-form requests (no schema anywhere) are unaffected
- All new code has test coverage including schema validation edge cases

---

## Amendment — PRD 0008 Interaction

**`output_schema` + tool use is mutually exclusive.** When PRD 0008 ships, if a request has an active `output_schema` (from ModelConfig or the request body) and tools are available for that request, Modela returns:

```json
{
  "error": "IncompatibleOptions",
  "message": "Structured outputs and tool use cannot be combined."
}
```

HTTP status: `422`.

**Why:** Anthropic's structured output mechanism injects a synthetic tool definition; adding real MCP tools alongside it produces ambiguous tool selection. For all providers, applying a JSON Schema constraint to a response that may be preceded by multiple tool-call rounds is undefined behaviour — the schema would need to apply to the final assistant turn only, which requires mid-loop schema awareness not yet designed. This restriction will be lifted in a future phase once the interaction is fully specified.

---

## Testing

**Schema resolution**
- `ModelConfig.output_schema` takes precedence over request-level `output_schema`
- Request `output_schema` is used when `ModelConfig.output_schema` is null
- Neither set → free-form response, no schema validation attempted

**OpenAI injection**
- `response_format` with the correct JSON Schema is forwarded to the provider when `output_schema` is active
- Conforming provider response returns parsed JSON object in `choices[0].message.content`

**Validation**
- Non-conforming provider response returns `502` with `validation_errors` array and `raw_content`
- Invalid `output_schema` in request body (not valid JSON Schema) returns `422` before hitting provider
- Valid schema with extra provider fields in response that don't break validation still passes

**PRD 0008 incompatibility**
- Request with active `output_schema` and non-empty `tools` field returns `422 IncompatibleOptions`
