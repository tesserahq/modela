"""Persistence for the provider model catalog check (PRD 0023).

The weekly task calls these functions inside a database session. They never
fetch from providers, so no connection is held during provider I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inference.adapters.base import BaseProviderAdapter
from app.inference.model_catalog_diff import ModelCatalogDiff
from app.models.provider_model_catalog import (
    ProviderModelCatalogEntry,
    ProviderModelCatalogSnapshot,
)

KIND_ADDED = "added"
KIND_REMOVED = "removed"
KIND_CHECK_FAILED = "check_failed"

ERROR_MISSING_KEY = "missing_key"
ERROR_NETWORK = "network"
ERROR_HTTP = "http_error"
ERROR_UNKNOWN = "unknown"


def categorize_fetch_error(exc: BaseException) -> str:
    """Map a fetch failure to a category. The message itself is never stored."""
    if isinstance(exc, ValueError) and "not configured" in str(exc):
        return ERROR_MISSING_KEY
    if isinstance(exc, httpx.HTTPStatusError):
        return ERROR_HTTP
    if isinstance(exc, httpx.TransportError):
        return ERROR_NETWORK
    return ERROR_UNKNOWN


def baseline_for(db: Session, adapter: BaseProviderAdapter) -> set[str]:
    """The ids to compare against: the last snapshot, or the curated list
    when there is no snapshot yet (the first run)."""
    snapshot = db.get(ProviderModelCatalogSnapshot, adapter.provider_id)
    if snapshot is not None:
        return set(snapshot.model_ids)
    return {model.id for model in adapter.list_models()}


def record_check_failure(
    db: Session, provider_id: str, error_category: str, now: datetime | None = None
) -> None:
    """Record a failed check. The snapshot is left unchanged (PRD 0023)."""
    db.add(
        ProviderModelCatalogEntry(
            provider_id=provider_id,
            kind=KIND_CHECK_FAILED,
            model_id=None,
            error_category=error_category,
            detected_at=now or datetime.now(UTC),
        )
    )


def record_check_success(
    db: Session,
    provider_id: str,
    diff: ModelCatalogDiff,
    live_in_scope_ids: set[str],
    now: datetime | None = None,
) -> None:
    """Record each detected change and replace the snapshot with what the
    provider reports now. Only called after a successful fetch."""
    detected_at = now or datetime.now(UTC)

    for model_id in diff.added:
        db.add(
            ProviderModelCatalogEntry(
                provider_id=provider_id,
                kind=KIND_ADDED,
                model_id=model_id,
                error_category=None,
                detected_at=detected_at,
            )
        )
    for model_id in diff.removed:
        db.add(
            ProviderModelCatalogEntry(
                provider_id=provider_id,
                kind=KIND_REMOVED,
                model_id=model_id,
                error_category=None,
                detected_at=detected_at,
            )
        )

    snapshot = db.get(ProviderModelCatalogSnapshot, provider_id)
    if snapshot is None:
        snapshot = ProviderModelCatalogSnapshot(provider_id=provider_id)
        db.add(snapshot)
    snapshot.model_ids = sorted(live_in_scope_ids)
    snapshot.captured_at = detected_at


def mark_reviewed(
    db: Session,
    entry: ProviderModelCatalogEntry,
    reviewer_id,
    now: datetime | None = None,
) -> ProviderModelCatalogEntry:
    entry.reviewed_at = now or datetime.now(UTC)
    entry.reviewed_by_id = reviewer_id
    db.flush()
    return entry


def clear_review(
    db: Session, entry: ProviderModelCatalogEntry
) -> ProviderModelCatalogEntry:
    entry.reviewed_at = None
    entry.reviewed_by_id = None
    db.flush()
    return entry


def find_entry(db: Session, entry_id) -> ProviderModelCatalogEntry | None:
    return db.scalar(
        select(ProviderModelCatalogEntry).where(
            ProviderModelCatalogEntry.id == entry_id
        )
    )
