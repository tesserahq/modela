# `app/services/`

Domain logic that doesn't belong in repositories or commands.

## What goes here

Code that:
- **Orchestrates multiple repositories** — reads from two or more data sources to produce a result
- **Applies non-trivial business rules** — logic too complex or reusable to live in a single command
- **Wraps an external concern with domain semantics** — e.g. translating a raw token exchange into "apply auth for this user"
- **Provides utilities shared across commands and repositories** — e.g. encryption helpers used by both a repository and a router

## What does NOT go here

| Code | Where it belongs |
|---|---|
| Simple DB reads / query builders | `repositories/` |
| Create / update / delete operations with side effects | `commands/` |
| Infrastructure plumbing (logging, Celery, tracing) | `infra/` |
| HTTP routing and request parsing | `routers/` |
| Provider integrations (OpenAI, etc.) | `providers/` |

## Current modules

| Module | Responsibility |
|---|---|
| `credential_applier.py` | Resolves a credential ID → auth headers; coordinates `CredentialRepository` and `MCPDelegatedTokenRepository`, handles all credential types (bearer, basic, API key, M2M, delegated) |
| `credentials.py` | Fernet encryption/decryption utilities and the credential field registry; used by the repository layer and routers |
