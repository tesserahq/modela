"""Pure diffing logic for provider model catalog drift detection.

Compares a provider adapter's curated model ids against its live model list,
scoped to that provider's chat-model id prefixes, with no I/O of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.provider import LiveProviderModel


@dataclass(frozen=True)
class ModelCatalogDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # Id of the newest in-scope live model, set only when it postdates every
    # currently curated model in the same family (or none of them are live
    # anymore) — a signal that a materially newer model showed up.
    newer_model_id: str | None = None


def diff_provider_models(
    curated_ids: set[str],
    live_models: list[LiveProviderModel],
    model_id_prefixes: tuple[str, ...],
) -> ModelCatalogDiff:
    in_scope = [m for m in live_models if m.id.startswith(model_id_prefixes)]
    live_ids = {m.id for m in in_scope}

    added = sorted(live_ids - curated_ids)
    removed = sorted(curated_ids - live_ids)

    newer_model_id: str | None = None
    if in_scope:
        newest_live = max(in_scope, key=lambda m: m.created_at)
        curated_created_ats = [m.created_at for m in in_scope if m.id in curated_ids]
        newest_curated_at = max(curated_created_ats) if curated_created_ats else None
        if newest_curated_at is None or newest_live.created_at > newest_curated_at:
            newer_model_id = newest_live.id

    return ModelCatalogDiff(added=added, removed=removed, newer_model_id=newer_model_id)
