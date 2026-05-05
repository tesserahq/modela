# PRD 0010 — Structured Outputs

> **Status:** Ready to implement.

## Overview

This phase adds structured output support: the ability to enforce a JSON Schema on the response returned by a ModelConfig. When `output_schema` is set on a ModelConfig, Modela builds a dynamic Pydantic model from the schema, passes it to pydantic-ai as `result_type`, and returns the validated JSON object to the caller.

---

## Goals

- Allow callers to receive validated, schema-conforming JSON responses from any LLM
- Enforce `output_schema` from ModelConfig when present
- Return a structured validation error if the provider response does not conform

---

## Non-Goals

- Per-request `output_schema` in the request body — deferred; ModelConfig is the only source in this pass
- Automatic schema generation from Python type annotations (caller-side concern)
- Coercing or auto-correcting non-conforming responses (fail fast, don't guess)
- Multi-provider structured output (covered in PRD 0003 for each new provider)
- Complex schema support (`$ref`, `oneOf`, `allOf`, `anyOf`) — callers must use flat, fully-inlined object schemas; these keywords return `422` with a clear message
- Streaming structured output — streaming is not yet implemented in Modela; this PRD applies to non-streaming only

---

## Background

Structured outputs remove the need for callers to parse or validate LLM responses themselves. Modela becomes the single enforcement point: convert the schema to a Pydantic model, pass it to pydantic-ai as `result_type`, receive the validated response, and return clean JSON or a clear error.

The `output_schema` field on `ModelConfig` was introduced in PRD 0001 and stored but not enforced. This PRD activates it.

pydantic-ai's `result_type` mechanism handles provider-specific injection (OpenAI uses `response_format: {type: "json_schema", strict: true}`) and response validation. Modela does not implement provider injection or schema coercion manually.

---

## Schema Format

Schemas are expressed as **JSON Schema (Draft 7)** objects. Only flat object schemas are supported in this pass: top-level `type: object` with scalar or array properties. Nested objects are allowed. The keywords `$ref`, `oneOf`, `allOf`, and `anyOf` are not supported and return `422`.

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

### `POST /chat/completions` — no request body changes

Per-request `output_schema` in the request body is deferred. The schema comes from `ModelConfig.output_schema` only.

### Response — structured output

When a schema is active, `choices[0].message.content` is a parsed JSON object instead of a string. `CompletionChoice.message` is widened from `dict[str, str]` to `dict[str, Any]` to accommodate this.

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

| Code  | Condition                                                                 |
| ----- | ------------------------------------------------------------------------- |
| `422` | `output_schema` uses unsupported keywords (`$ref`, `oneOf`, `allOf`, `anyOf`) |
| `422` | `output_schema` is not a valid flat object schema (e.g. top-level type is not `object`) |
| `502` | Provider returned output that failed schema validation                    |

The `502` body includes a `validation_errors` field with the Pydantic validation failures so callers can debug prompt/schema mismatches.

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

### JSON Schema → Pydantic model conversion

The core new logic is a translator function that converts a flat JSON Schema dict into a `pydantic.create_model()` call. This is the only genuinely new code in this PRD — implement and test it in isolation before wiring it into the command.

**Supported type mappings:**

| JSON Schema type          | Python type        |
| ------------------------- | ------------------ |
| `"string"`                | `str`              |
| `"number"`                | `float`            |
| `"integer"`               | `int`              |
| `"boolean"`               | `bool`             |
| `"array"` (items: scalar) | `list[<item_type>]`|
| `"object"` (nested)       | recursive          |

Fields listed in `"required"` are non-optional. Fields not in `"required"` get a default of `None` and are typed `Optional[T]`.

Schemas using `$ref`, `oneOf`, `allOf`, or `anyOf` at any level of nesting are rejected with `422` before reaching the provider.

`"enum"` on string fields is validated post-response via Pydantic's `Literal` type. `"minimum"` / `"maximum"` constraints are not enforced in v1 (the provider response is accepted if the type matches).

### pydantic-ai integration

In `CreateCompletionCommand.execute`:

1. After resolving `config`, check if `config.output_schema` is set.
2. If set: call the translator to build a dynamic Pydantic model. If the schema is unsupported, raise `422` immediately.
3. Construct the Agent with `result_type=dynamic_model` instead of the default `str`.
4. After `agent.run(...)`, call `result.output.model_dump()` and place the dict in `choices[0].message.content`.
5. If pydantic-ai raises a validation error on the provider response, catch it and raise `StructuredOutputValidationError` → `502`.

When `output_schema` is not set, the Agent is constructed as today (`result_type` defaults to `str`) and the response is unaffected.

### Tool use compatibility

**No incompatibility guard is needed.** pydantic-ai's `result_type` mechanism applies the schema to the final assistant response after all tool-call rounds are complete. Structured outputs and MCP tools can coexist on the same ModelConfig. The Amendment in the original PRD draft is superseded by this approach.

### ModelConfig admin update

The `output_schema` field on ModelConfig (introduced in PRD 0001) is now actively enforced. The CRUD API already supports reading/writing it. No schema or migration changes required.

---

## Dependencies

- PRD 0001 (foundation, ModelConfig, OpenAI adapter)
- pydantic-ai (already in use — no new dependency)
- No `jsonschema` library required

---

## Success Criteria

- ModelConfig with `output_schema` returns a validated JSON object in `choices[0].message.content`
- Free-form requests (no `output_schema` on ModelConfig) are unaffected
- Schema using `$ref`, `oneOf`, or `allOf` returns `422` with a clear unsupported-keyword message
- Non-conforming provider response returns `502` with `validation_errors`
- ModelConfig with both `output_schema` and MCP tools attached works correctly — tool rounds complete, then schema is applied to the final response
- All new code has test coverage including schema conversion edge cases

---

## Testing

**Schema conversion (unit tests — test the translator in isolation)**
- Scalar fields map to correct Python types
- Fields not in `required` become `Optional[T]` with default `None`
- Nested object schemas produce nested Pydantic models
- `$ref`, `oneOf`, `allOf`, `anyOf` raise `422` before any provider call
- Non-object top-level schema raises `422`

**Integration**
- ModelConfig with `output_schema` returns parsed JSON object in `choices[0].message.content`
- ModelConfig without `output_schema` returns string content as before
- Non-conforming provider response returns `502` with `validation_errors` array and `raw_content`
- ModelConfig with `output_schema` AND MCP tools attached completes tool rounds and applies schema to final response
