# PRD 0006 — BYOK & Credential Management

## Overview

This phase introduces **Bring Your Own Key (BYOK)**: the ability for consumers to supply their own provider API keys, stored securely in Modela and associated with a `project_id`. When a BYOK key is present for the resolved provider, it is used instead of the platform-managed key. Admins retain visibility over which projects have registered keys.

---

## Goals

- Allow consumers to register their own provider API keys against a `project_id`
- Store keys encrypted at rest using Fernet symmetric encryption (already available via `app/security/crypto.py`)
- Use a project's BYOK key when resolving the provider, falling back to the platform key if none exists
- Provide admin endpoints to list and revoke project keys (without exposing the key value)
- Support key rotation (re-register replaces the previous key)

---

## Non-Goals

- Per-request key injection via HTTP header (keys must be pre-registered, not sent per request)
- Fine-grained per-ModelConfig key assignment (key is associated with project + provider)
- Multi-key round-robin or key pools
- External secret managers (Vault, AWS Secrets Manager) — deferred

---

## Background

Platform-managed keys (PRD 0001) work for Tessera-operated deployments, but some consumers (e.g. Linden accounts) want to use their own provider accounts for cost attribution, quota control, or data residency reasons. BYOK gives them that control without exposing key management complexity to every caller.

The key resolution priority is:

1. Project has a BYOK key for the resolved provider → use it
2. Platform key configured in settings → use it
3. Neither → `502` with a clear error

---

## Data Model

**Table: `project_provider_keys`**

| Column          | Type         | Notes                                                            |
| --------------- | ------------ | ---------------------------------------------------------------- |
| `id`            | UUID         | Primary key                                                      |
| `project_id`    | UUID         | Tessera project identifier                                       |
| `provider`      | VARCHAR(100) | Provider name (e.g. `openai`, `anthropic`)                       |
| `encrypted_key` | TEXT         | Fernet-encrypted API key                                         |
| `key_hint`      | VARCHAR(20)  | Last 4 chars of the raw key, for identification (e.g. `...a3Kx`) |
| `created_at`    | TIMESTAMPTZ  |                                                                  |
| `updated_at`    | TIMESTAMPTZ  | Updated on rotation                                              |
| `deleted_at`    | TIMESTAMPTZ  | Soft delete (revocation)                                         |

**Constraint:** unique index on `(project_id, provider)` among non-deleted rows. One key per project per provider at a time.

---

## API

### Consumer endpoints

Consumers manage their own keys. Authentication is via the standard Tessera auth; `project_id` is derived from the authenticated context — consumers cannot register keys for other projects.

| Method   | Path               | Description                                                                    |
| -------- | ------------------ | ------------------------------------------------------------------------------ |
| `PUT`    | `/keys/{provider}` | Register or rotate a key for the caller's project + provider                   |
| `GET`    | `/keys`            | List registered providers for the caller's project (key values never returned) |
| `DELETE` | `/keys/{provider}` | Revoke the key for this provider                                               |

**`PUT /keys/{provider}` request body:**

```json
{
  "api_key": "sk-proj-..."
}
```

**`GET /keys` response:**

```json
{
  "keys": [
    {
      "provider": "openai",
      "key_hint": "...a3Kx",
      "updated_at": "2026-01-15T10:00:00Z"
    },
    {
      "provider": "anthropic",
      "key_hint": "...9mZp",
      "updated_at": "2026-02-01T08:30:00Z"
    }
  ]
}
```

The raw key is never returned after registration.

### Admin endpoints

Admins can view and revoke keys for any project. RBAC: `modela.project_keys:read` / `modela.project_keys:delete`.

| Method   | Path                                           | Description                             |
| -------- | ---------------------------------------------- | --------------------------------------- |
| `GET`    | `/admin/projects/{project_id}/keys`            | List registered providers for a project |
| `DELETE` | `/admin/projects/{project_id}/keys/{provider}` | Revoke a project's key                  |

---

## Key Resolution at Request Time

The credential resolver runs after ModelConfig is loaded and before the provider adapter is called:

```python
async def resolve_api_key(project_id: UUID, provider: str) -> str:
    byok = await project_provider_key_repo.get(project_id, provider)
    if byok:
        return decrypt(byok.encrypted_key)
    platform_key = settings.get_provider_key(provider)
    if platform_key:
        return platform_key
    raise CredentialNotFoundError(provider, project_id)
```

The resolved key is passed to the adapter for this request only — it is never cached in memory beyond the request lifecycle.

**Error response when no key is found:**

```json
{
  "error": "CredentialNotFound",
  "message": "No API key configured for provider 'openai' and this project."
}
```

HTTP status: `502`.

---

## Encryption

Keys are encrypted using Fernet (symmetric, already implemented in `app/security/crypto.py`). The encryption key is loaded from `settings.secret_key` (existing app secret).

- Encrypt on `PUT /keys/{provider}` before writing to DB
- Decrypt in `resolve_api_key` at request time
- The raw key is never logged, never returned in API responses, and never stored unencrypted

---

## Key Validation

On registration, Modela performs a lightweight validation call against the provider to confirm the key is valid before storing it:

- OpenAI: `GET /models` (cheapest available check)
- Anthropic: minimal `POST /messages` with `max_tokens: 1`
- Ollama: no key to validate (no-op)

If validation fails, the key is rejected with `422` and not stored.

---

## Audit Logging

Key registration, rotation, and revocation events are written to a structured log with `project_id`, `provider`, `key_hint`, and the acting user identity. These are not yet emitted to Eventa (that is PRD 0007), but the log records provide an audit trail.

---

## Dependencies

- PRD 0001 (project_id in request context, Fernet crypto already in app/security/)
- PRD 0003 (multiple providers to associate keys with)
- `app/security/crypto.py` (existing Fernet implementation)

---

## Success Criteria

- A consumer can register, view hint, and revoke their own provider key
- A registered BYOK key is used for all requests from that `project_id` + provider combination
- Platform key is used as fallback when no BYOK key exists
- No credential is resolved → `502` with `CredentialNotFound`
- Key values are never returned from any API endpoint
- Key values are stored encrypted and decrypted only at request time
- Invalid keys are rejected at registration (provider validation check)
- Admin endpoints can list and revoke keys for any project
- All key management operations are logged with audit detail

---

## Testing

**Key registration**
- `PUT /keys/{provider}` stores an encrypted key and returns `key_hint` (last 4 chars)
- Raw key value is never present in any API response
- Registering a second key for the same project + provider replaces the first (rotation)
- Invalid key rejected by provider validation returns `422` and is not stored

**Key resolution**
- Request from a project with a BYOK key uses that key (not the platform key)
- Request from a project without a BYOK key falls back to the platform key
- Neither key configured returns `502 CredentialNotFound`

**Encryption**
- Stored `encrypted_key` column is not the raw API key value
- Decrypted key at request time matches the original registered value

**Admin endpoints**
- Admin can list and revoke keys for any project
- Non-admin access to admin endpoints returns `403`

**Consumer endpoints**
- Consumer can only see and manage keys for their own project

**`ProjectProviderKeyRepository`**
- `get(project_id, provider)` returns the active key; returns `None` when none exists
- `get(project_id, provider)` returns `None` for a soft-deleted (revoked) key
- Unique constraint: creating a second active key for the same `project_id + provider` upserts (replaces) the existing row

**Commands**
- `register_project_key_command`: encrypts the raw key before writing; `key_hint` stored is the last 4 characters of the raw key
- `rotate_project_key_command`: replaces the existing encrypted value; `updated_at` is bumped
- `revoke_project_key_command`: soft-deletes the row; subsequent `get` returns `None`

**Router (`keys_router`)**
- `PUT /keys/{provider}` returns the created/updated record with `key_hint` but no raw key value
- `GET /keys` lists providers with hints; absent providers are not listed
- `DELETE /keys/{provider}` returns `204`; subsequent `GET /keys` no longer includes that provider
- `GET /admin/projects/{project_id}/keys` returns `403` for non-admins
