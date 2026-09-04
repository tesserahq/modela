# Modela

AI gateway service: resolves a named **ModelConfig** slug, forwards requests to a provider, and logs usage.

## Commands

```bash
# Dev server (hot reload)
poetry run dev           # or: poetry run uvicorn app.main:app --reload --port 8000

# Celery worker
poetry run worker

# Tests (ENV=test required — switches DB to modela_test)
ENV=test poetry run pytest
ENV=test poetry run pytest tests/routers/  # run a subset

# Migrations
poetry run alembic upgrade head
poetry run alembic revision --autogenerate -m "description"  # generate from models

# Lint / format
poetry run ruff check .        # lint
poetry run black .             # format
```

## Architecture

```
app/
  main.py               # App factory: create_app(testing, auth_middleware)
  config.py             # Settings (pydantic-settings). get_settings() is NOT cached.
  db.py                 # Base, SessionLocal, get_db, soft-delete session event

  models/               # SQLAlchemy ORM (Base + TimestampMixin + SoftDeleteMixin)
                        # Pure join tables (no surrogate PK) use sqlalchemy.Table() on Base.metadata — not an ORM class
  schemas/              # Pydantic v2 request/response schemas
  repositories/         # Data access — SoftDeleteRepository[T] base class
                        # Pagination query methods return Select; routers call paginate(db, repo.list_query(...))
  commands/             # Mutating operations only — CREATE/UPDATE/DELETE. For reads, routers call repositories directly (no command needed).
    model_configs/      # create_, update_, delete_model_config_command.py
    completions/        # create_completion_command.py
    summarize/          # create_summarize_command.py
  routers/
    utils/dependencies.py  # Shared FastAPI dependencies — get_<resource>_or_404 pattern for ID-based endpoints
  inference/            # Full model lifecycle: factory (build_model), ModelaModel wrapper, provider adapters
    model.py            # ModelaModel — pydantic-ai Model decorator; applies ModelConfig params and logs usage
    factory.py          # build_model(config, project_id, request_id) — single entry point for commands
    adapters/           # Provider adapters: BaseProviderAdapter ABC, registry, OpenAI + Anthropic implementations
  tasks/                # Celery tasks (fire-and-forget via .delay())
  auth/rbac.py          # build_rbac_dependencies() — wraps tessera-sdk authorize()
  exceptions/           # ResourceNotFoundError (404), ProviderError (502), ProviderTimeoutError (504)
  services/
    credential_applier.py  # Resolves credential_id → auth headers (5 types: Bearer, Basic, API key, M2M, delegated exchange)
    mcp/               # MCPToolset (pydantic-ai AbstractToolset adapter), MCPToolExecutor, ToolCatalog (Redis-cached), client_factory
  infra/               # Celery app, logging config, telemetry, server settings
```

## Key env vars

| Var | Default | Notes |
|-----|---------|-------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/modela` | |
| `TEST_DATABASE_URL` | `postgresql://...localhost.../modela_test` | resolved automatically when `ENV=test`; override only if DB is non-default |
| `ENV` | `development` | set to `test` for tests, `production` for prod |
| `DISABLE_AUTH` | `false` | set `true` locally to skip JWT middleware |
| `OPENAI_API_KEY` | — | required for OpenAI-backed requests |
| `ANTHROPIC_API_KEY` | — | required for Anthropic-backed requests |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Celery broker + backend |
| `CREDENTIAL_MASTER_KEY` | — | required for credential storage (AES encryption key) |
| `FERNET_KEY` | — | optional; legacy field, superseded by `CREDENTIAL_MASTER_KEY` |

## Gotchas

**Soft-delete is automatic.** A SQLAlchemy session event in `db.py` appends `WHERE deleted_at IS NULL` to every SELECT on any model that inherits `SoftDeleteMixin`. To query deleted rows, use `.execution_options(skip_soft_delete_filter=True)`.

**`get_settings()` has no cache.** It creates a fresh `Settings()` on every call. Fine for most uses, but avoid calling it in a tight loop.

**`Settings.ConfigDict` is broken.** The inner class form doesn't activate pydantic-settings' `.env` file loading. All config must come from real environment variables.

**Alembic autogenerate requires explicit model imports.** Add new model files to `alembic/env.py` (`import app.models` already handles models in `app/models/__init__.py`). If a model isn't imported before `target_metadata` is read, autogenerate won't detect it.

**New models need to be exported from `app/models/__init__.py`** so `alembic/env.py`'s `import app.models` picks them up.

**Adding a new provider:** implement `BaseProviderAdapter` in `app/inference/adapters/`, register it in `app/inference/adapters/registry.py`.

**`routers/utils/dependencies.py` is the canonical place for shared dependencies.** Use `ResourceNotFoundError` (not `HTTPException`) so the registered exception handler serializes the 404 response consistently. Note: `get_mcp_server_by_id` in that file still uses `HTTPException` directly — don't follow that example for new code.

**List endpoints use the SQLAlchemy paginate extension.** Import `from fastapi_pagination.ext.sqlalchemy import paginate` and pass `(db, select(...))` — not `paginate(list)`, which triggers a warning and loads all rows.

## Testing patterns

- `ENV=test` → uses `modela_test` DB; session-scoped engine runs `alembic upgrade head` on first use
- Each test gets a function-scoped DB session with transaction rollback (no truncation needed)
- `authorize()` is globally patched in `conftest.py` before any router imports
- `get_current_user` is overridden via `app.dependency_overrides`
- Use `create_client_fixture("fixture_name")` (defined in `tests/conftest.py`) to create typed test clients

## Python version

Requires **Python 3.14** (see `.tool-versions`). Managed via `asdf` or `mise`.
