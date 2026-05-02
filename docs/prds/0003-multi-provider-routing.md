# PRD 0003 — Multi-Provider & Routing

## Overview

This phase extends Modela to support multiple LLM providers. It introduces **Anthropic** and **Ollama** adapters and a provider registry that resolves a ModelConfig's `provider` field to the correct adapter at runtime. Consumers remain unaware of the underlying provider — only the ModelConfig slug changes.

---

## Goals

- Add Anthropic (Claude) and Ollama (local/self-hosted) provider adapters
- Introduce a provider registry: a map of provider identifier → adapter instance
- Extend ModelConfig validation to reject unknown `provider` values at write time
- Ensure all providers implement the `BaseProviderAdapter` interface from PRD 0001
- Maintain full OpenAI-compatible response shape regardless of provider

---

## Non-Goals

- Dynamic provider registration at runtime (providers are registered at startup)
- Weighted load balancing across providers (PRD 0005)
- Fallback chains (PRD 0005)
- Streaming (PRD 0004)
- Capability-based routing (e.g. "pick whichever provider supports vision")

---

## Background

PRD 0001 established `BaseProviderAdapter` and the OpenAI implementation. The adapter pattern was designed so adding a new provider means implementing one class and registering it — no changes to routing or request handling logic.

Each provider has a different native request/response format. The adapter layer is responsible for translating the internal `CompletionRequest` → provider format, and the provider response → `CompletionResponse`. Consumers and the rest of Modela only ever see the internal types.

---

## Provider Registry

A registry is a dict-like structure populated at application startup:

```python
PROVIDER_REGISTRY: dict[str, BaseProviderAdapter] = {
    "openai":    OpenAIAdapter(settings),
    "anthropic": AnthropicAdapter(settings),
    "ollama":    OllamaAdapter(settings),
}
```

Resolution at request time:
```python
adapter = PROVIDER_REGISTRY.get(model_config.provider)
if adapter is None:
    raise ProviderNotRegisteredError(model_config.provider)
```

**Startup validation:** if a provider is referenced by any ModelConfig in the DB but its adapter is not registered (e.g. missing API key), Modela logs a warning but does not fail to start. The error surfaces at request time.

---

## Anthropic Adapter

### Credential

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Request mapping

Anthropic's API (`/v1/messages`) differs from OpenAI in key ways:

| Concept | OpenAI | Anthropic |
|---------|--------|-----------|
| System prompt | `messages[0].role = "system"` | Top-level `system` field |
| Model param | `model` | `model` |
| Max tokens | `max_tokens` | `max_tokens` (required) |
| Response | `choices[0].message.content` | `content[0].text` |
| Token usage | `usage.prompt_tokens` / `completion_tokens` | `usage.input_tokens` / `output_tokens` |

The adapter handles all translation. The `system_prompt` from ModelConfig is extracted from the messages list and placed in the top-level `system` field before forwarding.

### Structured outputs (from PRD 0002)

Anthropic does not have a native `response_format` equivalent. Structured output is requested by injecting a tool definition that describes the output schema and instructing the model to call it:

```python
tools = [{
    "name": "structured_output",
    "description": "Return the response in the required format.",
    "input_schema": output_schema,
}]
tool_choice = {"type": "tool", "name": "structured_output"}
```

The response is extracted from `content[0].input` (tool use block) rather than `content[0].text`. The validation step (PRD 0002) then runs as normal.

### `extra_body`

Merged into the Anthropic request dict before sending, using `httpx` directly or the Anthropic SDK's equivalent passthrough mechanism.

---

## Ollama Adapter

Ollama exposes an OpenAI-compatible API at a configurable base URL. The Ollama adapter reuses the OpenAI SDK with a custom `base_url`:

```python
client = openai.AsyncOpenAI(
    api_key="ollama",  # Ollama ignores this
    base_url=settings.ollama_base_url,  # e.g. http://localhost:11434/v1
)
```

Because Ollama is OpenAI-compatible, no request/response translation is needed beyond what the OpenAI adapter already does. The Ollama adapter is a thin subclass.

### Credential

No API key. Configuration is:
```
OLLAMA_BASE_URL=http://localhost:11434
```

If `OLLAMA_BASE_URL` is not set, the Ollama adapter is not registered (optional provider).

### Structured outputs

Ollama's structured output support depends on the underlying model. When `output_schema` is active, the adapter injects `response_format` identically to the OpenAI adapter. If the model does not support it, Ollama returns an error that surfaces as a `502`.

---

## ModelConfig Validation

When a ModelConfig is created or updated, the `provider` field is validated against the set of registered providers:

```python
if config.provider not in PROVIDER_REGISTRY:
    raise ValidationError(f"Unknown provider '{config.provider}'. "
                          f"Registered providers: {list(PROVIDER_REGISTRY.keys())}")
```

This prevents creating ModelConfigs that can never be resolved.

---

## Settings Changes

```python
class Settings(BaseSettings):
    # Existing
    openai_api_key: str | None = None

    # New
    anthropic_api_key: str | None = None
    ollama_base_url: str | None = None
```

---

## Provider-to-Response Normalisation

All adapters must produce a `CompletionResponse` with identical fields regardless of provider. The internal shape (defined in PRD 0001) is the contract. The response returned to the consumer is the OpenAI-compatible JSON shape, constructed from `CompletionResponse`, not from the raw provider response.

The `raw` field on `CompletionResponse` still contains the unmodified provider response for debugging.

---

## Dependencies

- PRD 0001 (BaseProviderAdapter, ModelConfig, usage logging)
- PRD 0002 (structured output injection — Anthropic tool-calling approach)
- `anthropic` Python SDK (new dependency)
- `openai` Python SDK already present (reused for Ollama)

---

## Success Criteria

- A ModelConfig with `provider: "anthropic"` successfully routes to Claude and returns an OpenAI-compatible response
- A ModelConfig with `provider: "ollama"` routes to the local Ollama instance
- Creating a ModelConfig with an unknown provider returns a `422` validation error
- `system_prompt` from ModelConfig is correctly placed in Anthropic's top-level `system` field
- Structured outputs via PRD 0002 work with both Anthropic (tool-based) and Ollama
- `extra_body` passthrough works for all three providers
- Usage records are written correctly for all providers
- All new adapters have integration tests (can be skipped in CI without provider credentials via env flag)
