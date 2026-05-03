"""
Utilities for building indexing-related CloudEvents payloads.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from tessera_sdk.infra.events.event import Event, event_type, event_source

# Indexing event types
ENTITY_INDEXED = "indexing.entity.indexed"
ENTITY_INDEXING_FAILED = "indexing.entity.indexing_failed"


def build_entity_indexed_event(
    entity_type: str,
    entity_id: str,
    provider: str,
    document_id: Optional[str] = None,
    user_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
) -> Event:
    """
    Create a CloudEvent for successful entity indexing.

    Args:
        entity_type: The type of entity (e.g., "pets")
        entity_id: The ID of the entity
        provider: The search provider name (e.g., "algolia")
        document_id: The document ID in the search provider
        user_id: Optional user ID associated with the entity
        project_id: Optional project ID associated with the entity

    Returns:
        Event: CloudEvent for entity indexed
    """
    document_id = document_id or f"{entity_type}_{entity_id}"
    return Event(
        source=event_source(f"/indexing/{entity_type}/{entity_id}"),
        event_type=event_type(ENTITY_INDEXED),
        privy=True,
        event_data={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider": provider,
            "document_id": document_id,
        },
        subject=f"{entity_type}/{entity_id}",
        user_id=str(user_id) if user_id else None,
        project_id=str(project_id) if project_id else None,
        labels={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider": provider,
        },
        tags=[
            f"entity_type:{entity_type}",
            f"entity_id:{entity_id}",
            f"provider:{provider}",
        ],
    )


def build_entity_indexing_failed_event(
    entity_type: str,
    entity_id: str,
    provider: str,
    error_message: str,
    user_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
) -> Event:
    """
    Create a CloudEvent for failed entity indexing.

    Args:
        entity_type: The type of entity (e.g., "pets")
        entity_id: The ID of the entity
        provider: The search provider name (e.g., "algolia")
        error_message: The error message describing the failure
        user_id: Optional user ID associated with the entity
        project_id: Optional project ID associated with the entity

    Returns:
        Event: CloudEvent for entity indexing failed
    """
    return Event(
        source=event_source(f"/indexing/{entity_type}/{entity_id}"),
        event_type=event_type(ENTITY_INDEXING_FAILED),
        privy=True,
        event_data={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider": provider,
            "error": error_message,
        },
        subject=f"{entity_type}/{entity_id}",
        user_id=str(user_id) if user_id else None,
        project_id=str(project_id) if project_id else None,
        labels={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider": provider,
            "status": "failed",
        },
        tags=[
            f"entity_type:{entity_type}",
            f"entity_id:{entity_id}",
            f"provider:{provider}",
            "status:failed",
        ],
    )
