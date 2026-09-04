"""
Utilities for building provider-model-catalog-drift CloudEvents payloads.
"""

from __future__ import annotations

from tessera_sdk.infra.events.event import (  # type: ignore[import-untyped]
    Event,
    event_source,
    event_type,
)

from app.inference.model_catalog_diff import ModelCatalogDiff

# Provider model catalog events
PROVIDER_MODEL_ADDED = "provider_model.added"
PROVIDER_MODEL_REMOVED = "provider_model.removed"


def build_provider_model_added_event(provider_id: str, diff: ModelCatalogDiff) -> Event:
    """Build a CloudEvent for models the provider serves that we don't curate yet."""
    event_data: dict[str, object] = {
        "provider_id": provider_id,
        "model_ids": diff.added,
    }
    if diff.newer_model_id is not None:
        event_data["newer_model_id"] = diff.newer_model_id

    return Event(
        source=event_source(),
        event_type=event_type(PROVIDER_MODEL_ADDED),
        event_data=event_data,
        subject=f"/providers/{provider_id}/models",
        labels={"provider_id": provider_id},
        tags=[f"provider_id:{provider_id}"],
    )


def build_provider_model_removed_event(
    provider_id: str, diff: ModelCatalogDiff
) -> Event:
    """Build a CloudEvent for curated ids the provider no longer serves."""
    event_data: dict[str, object] = {
        "provider_id": provider_id,
        "model_ids": diff.removed,
    }

    return Event(
        source=event_source(),
        event_type=event_type(PROVIDER_MODEL_REMOVED),
        event_data=event_data,
        subject=f"/providers/{provider_id}/models",
        labels={"provider_id": provider_id},
        tags=[f"provider_id:{provider_id}"],
    )
