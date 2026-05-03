# PRD 0003 — Multi-Provider & Routing

## Overview

This phase extends Modela to support Anthropic (Claude) and Ollama alongside OpenAI. Rather than writing new adapter classes, providers are added by registering pydantic-ai's built-in model types inside `ModelaModel` — the gateway interceptor introduced in PRD 0008. pydantic-ai handles all provider-specific format translation (messages, tool calls, streaming). Modela's gateway concerns (ModelConfig resolution, usage logging, BYOK key lookup, resilience) remain in `ModelaModel`.

---

## Goals

- Add Anthropic and Ollama as supported providers
- Extend `ModelaModel` with a provider factory that maps `ModelConfig.provider` → the appropriate pydantic-ai model
- Extend ModelConfig validation to reject unknown `provider` values at write time
- Maintain full OpenAI-compatible response shape regardless of provider (pydantic-ai normalises this)
- Remove `BaseProviderAdapter`, `CompletionResponse`, and `PROVIDER_REGISTRY` — these are superseded by the `ModelaModel` architecture (see PRD 0001 amendment, PRD 0008)

---

## Non-Goals

- Dynamic provider registration at runtime
- Weighted load balancing across providers (PRD 0005)
- Fallback chains (PRD 0005)
- Streaming (PRD 0004)
- Capability-based routing (e.g. "pick whichever provider supports vision")

---

## Background

PRD 0001 shipped the OpenAI adapter as a temporary foundation. PRD 0008 replaced it with `ModelaModel`, a pydantic-ai `Model` implementation that wraps a pydantic-ai native model and intercepts each call for gateway concerns. Adding a new provider in this architecture is a matter of extending the `ModelaModel` factory — no new adapter class, no format translation code, no registry dict to maintain.

pydantic-ai supports OpenAI, Anthropic, Ollama (via its OpenAI-compatible API), Gemini, Groq, and others natively. For Modela, adding a provider means:

1. Add its API key / config to `Settings`
2. Add a branch to `_build_inner_model()` in `ModelaModel`
3. Add its identifier to the `SUPPORTED_PROVIDERS` list used for ModelConfig validation

---

## `ModelaModel` Provider Factory

`ModelaModel` is introduced in PRD 0008. This PRD extends its factory to cover Anthropic and Ollama:

```python
def _build_inner_model(
    model_config: ModelConfig,
    api_key: str,
    settings: Settings,
) -> pydantic_ai.models.Model:
    match model_config.provider:
        case "openai":
            return OpenAIModel(
                model_config.model,
                provider=OpenAIProvider(api_key=api_key),
            )
        case "anthropic":
            return AnthropicModel(
                model_config.model,
                provider=AnthropicProvider(api_key=api_key),
            )
        case "ollama":
            return OpenAIModel(
                model_config.model,
                provider=OpenAIProvider(
                    api_key="ollama",
                    base_url=settings.ollama_base_url,
                ),
            )
        case _:
            raise ProviderNotRegisteredError(model_config.provider)
```

Ollama reuses `OpenAIModel` with a custom `base_url` — no separate implementation needed since Ollama exposes an OpenAI-compatible API.

---

## Provider Credentials

### Anthropic

```
ANTHROPIC_API_KEY=sk-ant-...
```

Resolved via BYOK logic (PRD 0006): project key takes precedence over the platform key in `Settings`. `ModelaModel` receives the resolved key before constructing the inner `AnthropicModel`.

### Ollama

No API key. Configuration:

```
OLLAMA_BASE_URL=http://localhost:11434
```

If `OLLAMA_BASE_URL` is not set, `"ollama"` is excluded from `SUPPORTED_PROVIDERS` and ModelConfig validation rejects it.

---

## Structured Outputs — Anthropic (from PRD 0002)

Anthropic does not support `response_format`. When `output_schema` is active and the provider is Anthropic, `ModelaModel.request()` injects a synthetic tool before delegating to the inner `AnthropicModel`:

```python
# Injected into the request before calling self._inner.request()
synthetic_tools = [{
    "name": "structured_output",
    "description": "Return the response in the required format.",
    "input_schema": output_schema,
}]
tool_choice = {"type": "tool", "name": "structured_output"}
```

The response is extracted from the tool use block (`content[0].input`) rather than `content[0].text`. The validation step (PRD 0002) runs as normal.

This injection is handled entirely within `ModelaModel` — no changes to the router or command layer are needed for Anthropic structured output support.

---

## ModelConfig Validation

`SUPPORTED_PROVIDERS` is a list derived from which providers are configured at startup:

```python
SUPPORTED_PROVIDERS = ["openai"]
if settings.anthropic_api_key:
    SUPPORTED_PROVIDERS.append("anthropic")
if settings.ollama_base_url:
    SUPPORTED_PROVIDERS.append("ollama")
```

When a ModelConfig is created or updated, the `provider` field is validated against this list:

```python
if config.provider not in SUPPORTED_PROVIDERS:
    raise ValidationError(
        f"Unknown provider '{config.provider}'. "
        f"Supported: {SUPPORTED_PROVIDERS}"
    )
```

---

## Settings Changes

```python
class Settings(BaseSettings):
    # Existing
    openai_api_key: str | None = None

    # New
    anthropic_api_key: str | None = None
    ollama_base_url:   str | None = None
```

---

## Dependencies

- PRD 0001 (ModelConfig, usage logging)
- PRD 0008 (`ModelaModel` and the provider factory — must ship first)
- `pydantic-ai[anthropic]` (adds Anthropic support to pydantic-ai)
- `openai` Python SDK already present (reused for Ollama via pydantic-ai)

---

## Success Criteria

- A ModelConfig with `provider: "anthropic"` successfully routes to Claude and returns an OpenAI-compatible response
- A ModelConfig with `provider: "ollama"` routes to the local Ollama instance
- Creating a ModelConfig with an unknown provider returns a `422` validation error
- `system_prompt` from ModelConfig is correctly applied for Anthropic requests (pydantic-ai places it in the top-level `system` field)
- Structured outputs (PRD 0002) work for Anthropic via the synthetic tool injection in `ModelaModel`
- Structured outputs work for Ollama via `response_format` (model-dependent; provider error surfaces as `502` if unsupported)
- `extra_body` passthrough works for all three providers
- Usage records are written correctly for all providers
- Ollama provider is excluded from `SUPPORTED_PROVIDERS` when `OLLAMA_BASE_URL` is not set
- All new provider paths have integration tests (skippable in CI without credentials via env flag)

---

## Testing

**ModelaModel factory**
- `provider: "anthropic"` builds an `AnthropicModel` inner model
- `provider: "ollama"` builds an `OpenAIModel` with the configured `base_url`
- Unknown provider raises `ProviderNotRegisteredError`
- `OLLAMA_BASE_URL` unset → `"ollama"` absent from `SUPPORTED_PROVIDERS`

**Anthropic provider** (integration, skippable without `ANTHROPIC_API_KEY`)
- Completion request routes to Anthropic and returns an OpenAI-compatible response
- `system_prompt` from ModelConfig is placed in Anthropic's top-level `system` field, not in `messages`
- Anthropic structured output (PRD 0002): synthetic tool is injected and response is extracted from tool use block

**Ollama provider** (integration, skippable without `OLLAMA_BASE_URL`)
- Completion request routes to the Ollama base URL and returns an OpenAI-compatible response

**ModelConfig validation**
- Creating a ModelConfig with `provider: "anthropic"` succeeds when `ANTHROPIC_API_KEY` is set
- Creating a ModelConfig with an unsupported provider returns `422`
