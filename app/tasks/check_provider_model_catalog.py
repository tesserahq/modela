from tessera_sdk.infra.events.event import Event  # type: ignore[import-untyped]
from tessera_sdk.infra.events.nats_router import (
    NatsEventPublisher,  # type: ignore[import-untyped]
)

from app.db import session_scope
from app.events.provider_model_events import (
    build_provider_model_added_event,
    build_provider_model_removed_event,
)
from app.inference.adapters.base import BaseProviderAdapter
from app.inference.adapters.registry import PROVIDER_REGISTRY
from app.inference.model_catalog_diff import diff_provider_models
from app.infra.celery_app import celery_app
from app.infra.logging_config import get_logger
from app.services.provider_catalog_history import (
    baseline_for,
    categorize_fetch_error,
    record_check_failure,
    record_check_success,
)

logger = get_logger("check_provider_model_catalog_task")


@celery_app.task
def check_provider_model_catalog_task() -> None:
    """Weekly check: diff each provider's live model list against the last
    snapshot (or the curated list on the first run), record changes, and
    publish NATS events for them (PRD 0018, PRD 0023)."""
    publisher = NatsEventPublisher()
    for adapter in PROVIDER_REGISTRY.values():
        try:
            _check_adapter(adapter, publisher)
        except Exception:
            # One provider's failure must not stop the others.
            logger.exception(
                "Catalog check failed unexpectedly for '%s'", adapter.provider_id
            )


def _check_adapter(adapter: BaseProviderAdapter, publisher: NatsEventPublisher) -> None:
    try:
        live_models = adapter.fetch_live_model_ids()
    except Exception as exc:
        category = categorize_fetch_error(exc)
        logger.exception(
            "Failed to fetch live model list for provider '%s' (%s); recording check_failed",
            adapter.provider_id,
            category,
        )
        with session_scope() as db:
            record_check_failure(db, adapter.provider_id, category)
        return

    live_in_scope_ids = {
        model.id
        for model in live_models
        if model.id.startswith(adapter.model_id_prefixes)
    }

    # Write the changes and the new snapshot in one transaction. No provider
    # call happens inside this session.
    with session_scope() as db:
        baseline = baseline_for(db, adapter)
        diff = diff_provider_models(baseline, live_models, adapter.model_id_prefixes)
        record_check_success(db, adapter.provider_id, diff, live_in_scope_ids)

    if diff.added:
        _publish(
            publisher,
            build_provider_model_added_event(adapter.provider_id, diff),
            adapter.provider_id,
            "added",
        )
    if diff.removed:
        _publish(
            publisher,
            build_provider_model_removed_event(adapter.provider_id, diff),
            adapter.provider_id,
            "removed",
        )


def _publish(
    publisher: NatsEventPublisher, event: Event, provider_id: str, direction: str
) -> None:
    logger.info(
        "Publishing provider_model.%s event for '%s': %s",
        direction,
        provider_id,
        event.model_dump_json(),
    )
    try:
        publisher.publish_sync(event, event.event_type)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception(
            "Failed to publish provider_model.%s event for '%s'",
            direction,
            provider_id,
        )
