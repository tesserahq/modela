# PRD 0002 — System Prompt Model

## Overview

This phase introduces a first-class `SystemPrompt` resource with full version history, and replaces the inline `system_prompt: Text` field on `ModelConfig` with a foreign-key reference to it. Operators manage prompts independently of model configs; Modela resolves the current version at completion time.

The `SystemPrompt` CRUD infrastructure (migration, router, repository, schemas) was partially built before this PRD. This PRD completes it and activates the `ModelConfig` integration.

---

## Goals

- Store system prompts as versioned, named resources independent of any ModelConfig
- Allow ModelConfig to reference a SystemPrompt by UUID instead of embedding text
- Resolve the current version of the referenced SystemPrompt at completion request time
- Block deletion of a SystemPrompt that is still referenced by one or more ModelConfigs
- Complete the partially-built SystemPrompt CRUD layer (ORM models, commands, router registration)

---

## Non-Goals

- Pinning a specific version on ModelConfig (always uses current version)
- Keeping the inline `system_prompt: Text` field as a fallback
- Embedding SystemPrompt content in ModelConfig read responses
- Per-request system prompt override

---

## Background

`ModelConfig` was introduced in PRD 0001 with a plain `system_prompt: Text` field. This works for simple cases but has no history, no reuse across configs, and no promotion workflow. A dedicated `SystemPrompt` model with version history allows operators to update prompts independently, track changes, and share a single prompt across multiple model configs.

---

## Data Model

### New tables (already migrated — `2026_05_02_0003_add_system_prompts_tables.py`)

```
system_prompts
  id                  UUID PK
  name                VARCHAR(64) UNIQUE NOT NULL
  current_version_id  UUID FK → system_prompt_versions.id (SET NULL on delete)
  created_at          TIMESTAMP
  updated_at          TIMESTAMP

system_prompt_versions
  id                  UUID PK
  system_prompt_id    UUID FK → system_prompts.id (CASCADE on delete)
  content             TEXT NOT NULL
  version_number      INTEGER NOT NULL
  note                VARCHAR(512)
  created_at          TIMESTAMP
```

### ModelConfig change

Remove `system_prompt TEXT` column. Add:

```
model_configs
  system_prompt_id    UUID FK → system_prompts.id (RESTRICT on delete), nullable
```

**Migration:** drop the `system_prompt` column and its data (development stage — no production data to preserve), add the `system_prompt_id` column.

**On-delete RESTRICT:** deleting a `SystemPrompt` that any `ModelConfig` references returns a 409 error. Operators must reassign or clear all referencing ModelConfigs first.

---

## API

### SystemPrompt CRUD — `/system-prompts`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/system-prompts` | List all prompts (paginated) |
| `POST` | `/system-prompts` | Create prompt with initial version |
| `GET` | `/system-prompts/{name}` | Get prompt metadata |
| `PATCH` | `/system-prompts/{name}` | Rename prompt |
| `DELETE` | `/system-prompts/{name}` | Delete prompt — **409** if any ModelConfig references it |
| `GET` | `/system-prompts/{name}/current` | Get current version content + version info |
| `GET` | `/system-prompts/{name}/versions` | List version history (newest first, paginated) |
| `POST` | `/system-prompts/{name}/versions` | Create new version — becomes current immediately |

### ModelConfig changes

`system_prompt` field removed from all ModelConfig schemas. Replaced by:

- **Create/Update request:** `system_prompt_id: UUID | null`
- **Read response:** `system_prompt_id: UUID | null`

Callers that need the prompt content call `GET /system-prompts/{name}/current` separately.

### Errors

| Code | Condition |
|------|-----------|
| `404` | SystemPrompt not found |
| `409` | Attempt to delete a SystemPrompt referenced by one or more ModelConfigs |

---

## Completion Flow Change

`CreateCompletionCommand` currently reads `model_config.system_prompt` directly. After this PRD:

1. If `model_config.system_prompt_id` is set, load `system_prompt.current_version.content` from the DB
2. Pass the resolved content to the provider adapter as `instructions` (same as before)
3. If `system_prompt_id` is null, proceed with no system prompt

The resolution adds one DB read per completion when a system prompt is configured.

---

## Implementation Checklist

The following pieces are already built and need no changes:

- Migration file (`2026_05_02_0003_add_system_prompts_tables.py`)
- Pydantic schemas (`app/schemas/system_prompt.py`)
- Repository (`app/repositories/system_prompt_repository.py`)

Work required:

1. **ORM models** — create `app/models/system_prompt.py` with `SystemPrompt` and `SystemPromptVersion` classes; export from `app/models/__init__.py`
2. **Commands** — create `app/commands/system_prompts/` with `CreateSystemPromptCommand`, `UpdateSystemPromptCommand`, `DeleteSystemPromptCommand` (mirror `model_configs/` pattern; `DeleteSystemPromptCommand` enforces RESTRICT via a referencing-config check before deletion)
3. **Router registration** — add `system_prompts_router` to `app/main.py`
4. **ModelConfig migration** — new Alembic revision: drop `system_prompt`, add `system_prompt_id FK`
5. **ModelConfig ORM** — remove `system_prompt` column, add `system_prompt_id` + relationship
6. **ModelConfig schemas** — remove `system_prompt` field, add `system_prompt_id: Optional[UUID]`
7. **Completion command** — resolve system prompt content from FK before forwarding to provider
8. **Tests** — cover all items above (see Testing section)

---

## Dependencies

- PRD 0001 (ModelConfig, OpenAI adapter)

---

## Success Criteria

- CRUD endpoints for SystemPrompt and SystemPromptVersion are functional
- Creating a new version immediately makes it the current version
- Deleting a SystemPrompt referenced by a ModelConfig returns 409
- Deleting an unreferenced SystemPrompt succeeds and cascades versions
- ModelConfig create/update accepts `system_prompt_id`; references a valid SystemPrompt
- Completion with a referenced SystemPrompt uses the current version content
- Completion with `system_prompt_id: null` proceeds without a system prompt
- The old inline `system_prompt` field is gone from all ModelConfig API responses and DB

---

## Testing

**SystemPrompt CRUD**
- Create prompt → initial version is created, `current_version_id` is set
- Create new version → becomes current; old version still in history
- List versions → newest first
- Rename prompt → name updates, all references intact
- Delete unreferenced prompt → succeeds, versions cascade-deleted
- Delete prompt referenced by a ModelConfig → 409

**ModelConfig integration**
- Create ModelConfig with valid `system_prompt_id` → succeeds
- Create ModelConfig with non-existent `system_prompt_id` → 404
- Create ModelConfig with `system_prompt_id: null` → succeeds
- Read ModelConfig → returns `system_prompt_id`, not `system_prompt` text

**Completion resolution**
- Completion with `system_prompt_id` set → current version content passed to provider as instructions
- Completion with `system_prompt_id: null` → no instructions passed
- Promoting a new SystemPrompt version → subsequent completions use new content
