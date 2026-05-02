# Modela — AI Gateway Service (Tessera)

## Overview

Modela is a lightweight AI gateway service within the Tessera framework. It provides a unified entry point for interacting with multiple Large Language Model (LLM) providers while preserving each provider’s native capabilities.

Modela is designed to be minimal, composable, and infrastructure-focused. It avoids heavy abstractions and instead focuses on routing, control, and observability.

---

## Goals

- Provide a single, consistent entry point for all LLM interactions
- Support multiple providers without enforcing a unified schema
- Enable routing, failover, and provider selection strategies
- Centralize credential management and access control
- Offer observability and usage tracking
- Keep the system simple and extensible

---

## Non-Goals

- Not a full orchestration framework (handled by Quore)
- Not a workflow engine (handled by Orcha)
- Not a RAG system (can integrate with other services)
- Not a schema translation layer between providers

---

## Core Concepts

### 1. Native Provider Requests

Modela does not transform requests into a unified schema. Instead, it forwards requests in the native format of each provider.

Benefits:

- No feature loss
- Immediate support for new provider capabilities
- Lower maintenance overhead

---

### 2. Provider Abstraction (Minimal)

Providers are registered in Modela with:

- Name (e.g., `openai`, `anthropic`, `ollama`)
- Base URL / SDK configuration
- Authentication method
- Optional metadata (cost, latency hints, capabilities)

Modela abstracts connection and configuration, not request structure.

---

### 3. Routing Layer

Modela includes a routing system responsible for selecting which provider/model to use.

Routing strategies may include:

- Static routing (explicit provider/model)
- Fallback chains (failover on error)
- Weighted distribution (load balancing)
- Capability-based routing (e.g., vision, function calling)

---

### 4. Failover and Resilience

Modela can automatically retry requests across providers when failures occur.

Features:

- Retry policies
- Fallback provider chains
- Timeout handling
- Circuit breaking (future extension)

---

### 5. Credential Management

Modela centralizes API key and credential handling.

Supports:

- Bring Your Own Key (BYOK)
- Platform-managed keys
- Per-user or per-project credentials

This removes the need for downstream services to manage provider credentials.

---

### 6. Usage Tracking and Cost Control

Modela tracks usage across providers.

Capabilities:

- Token usage tracking
- Request counting
- Cost estimation per provider
- Per-user / per-project limits
- Quotas and rate limiting
- Consumer usage attribution via Tessera `project_id` associations

Usage must be measurable not only by provider, but also by the products consuming Modela. Tessera handles this by associating usage with a `project_id`, allowing downstream services to understand which product context is consuming AI resources and how those resources are being used.

For example, Linden is built around the Tessera framework and should be able to measure Modela usage at the account level. In Linden's context, the `project_id` maps to the Linden `account_id`, so usage, cost, limits, and audit trails can be attributed to the account consuming the resources.

---

### 7. Observability

Modela integrates with the Tessera observability stack.

Includes:

- Structured logging
- Distributed tracing (OpenTelemetry)
- Metrics (latency, error rate, usage)

This enables debugging, monitoring, and optimization of AI usage.

---

### 8. API Design

Modela exposes a simple API surface.

Example responsibilities:

- Forward requests to providers
- Apply routing rules
- Enforce limits and policies
- Return provider responses transparently

The API remains thin and predictable.

---

### 9. Extensibility

Modela is designed to evolve without breaking existing integrations.

Future extensions may include:

- Policy-based routing
- Caching layer (response or embedding cache)
- Streaming support improvements
- Provider capability registry
- Integration with Modela for semantic retrieval

---

## Architecture Position

Modela sits between application services and external AI providers.

```
Application Services (Conversa, Linden, etc.)
                ↓
             Modela
                ↓
    LLM Providers (OpenAI, Anthropic, Ollama)
```

---

## Integration with Tessera

Modela integrates with other Tessera services:

- **Identies**: authentication and API key association
- **Custos**: access control and permissions
- **Eventa**: emitting usage and audit events
- **Quore**: higher-level AI orchestration

Modela remains focused on execution, not reasoning.

---

## Design Principles

- Keep it simple
- Avoid unnecessary abstractions
- Preserve provider-native capabilities
- Be infrastructure-first, not feature-heavy
- Enable composition with other services

---

## Summary

Modela is a minimal AI gateway that provides routing, control, and observability for LLM usage within Tessera. It enables multi-provider support without sacrificing flexibility or introducing heavy abstractions.
