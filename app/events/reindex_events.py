"""
Utilities for building reindexing-related CloudEvents payloads.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from tessera_sdk.infra.events.event import Event, event_type, event_source

# Reindex event types
REINDEX_JOB_STARTED = "indexing.reindex.started"
REINDEX_JOB_COMPLETED = "indexing.reindex.completed"
REINDEX_JOB_FAILED = "indexing.reindex.failed"


def build_reindex_job_started_event(
    job_id: UUID,
    scope: str,
    domains: Optional[list[str]] = None,
    entity_types: Optional[list[str]] = None,
    providers: Optional[list[str]] = None,
) -> Event:
    """
    Create a CloudEvent for reindex job started.

    Args:
        job_id: The ID of the reindex job
        scope: The scope of the reindex job
        domains: Optional list of domain prefixes
        entity_types: Optional list of entity types
        providers: Optional list of provider names

    Returns:
        Event: CloudEvent for reindex job started
    """
    return Event(
        source=event_source(f"/reindex/{job_id}"),
        event_type=event_type(REINDEX_JOB_STARTED),
        privy=True,
        event_data={
            "job_id": str(job_id),
            "scope": scope,
            "domains": domains or [],
            "entity_types": entity_types or [],
            "providers": providers or [],
        },
        subject=f"/reindex/{job_id}",
        labels={
            "job_id": str(job_id),
            "scope": scope,
            "status": "started",
        },
        tags=[
            f"job_id:{str(job_id)}",
            f"scope:{scope}",
            "status:started",
        ],
    )


def build_reindex_job_completed_event(
    job_id: UUID,
    scope: str,
    total_entities: int,
    providers: Optional[list[str]] = None,
) -> Event:
    """
    Create a CloudEvent for reindex job completed.

    Args:
        job_id: The ID of the reindex job
        scope: The scope of the reindex job
        total_entities: Total number of entities indexed
        providers: Optional list of provider names

    Returns:
        Event: CloudEvent for reindex job completed
    """
    return Event(
        source=event_source(f"/reindex/{job_id}"),
        event_type=event_type(REINDEX_JOB_COMPLETED),
        privy=True,
        event_data={
            "job_id": str(job_id),
            "scope": scope,
            "total_entities": total_entities,
            "providers": providers or [],
        },
        subject=f"/reindex/{job_id}",
        labels={
            "job_id": str(job_id),
            "scope": scope,
            "status": "completed",
        },
        tags=[
            f"job_id:{str(job_id)}",
            f"scope:{scope}",
            "status:completed",
        ],
    )


def build_reindex_job_failed_event(
    job_id: UUID,
    scope: str,
    error_message: str,
) -> Event:
    """
    Create a CloudEvent for reindex job failed.

    Args:
        job_id: The ID of the reindex job
        scope: The scope of the reindex job
        error_message: The error message describing the failure

    Returns:
        Event: CloudEvent for reindex job failed
    """
    return Event(
        source=event_source(f"/reindex/{job_id}"),
        event_type=event_type(REINDEX_JOB_FAILED),
        privy=True,
        event_data={
            "job_id": str(job_id),
            "scope": scope,
            "error": error_message,
        },
        subject=f"/reindex/{job_id}",
        labels={
            "job_id": str(job_id),
            "scope": scope,
            "status": "failed",
        },
        tags=[
            f"job_id:{str(job_id)}",
            f"scope:{scope}",
            "status:failed",
        ],
    )
