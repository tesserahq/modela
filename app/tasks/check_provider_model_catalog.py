from tessera_sdk.infra.events.event import Event  # type: ignore[import-untyped]
from tessera_sdk.infra.events.nats_router import (
    NatsEventPublisher,  # type: ignore[import-untyped]
)

from app.events.provider_model_events import (
    build_provider_model_added_event,
    build_provider_model_removed_event,
)
from app.inference.adapters.base import BaseProviderAdapter
from app.inference.adapters.registry import PROVIDER_REGISTRY
from app.inference.model_catalog_diff import diff_provider_models
from app.infra.celery_app import celery_app
from app.infra.logging_config import get_logger

logger = get_logger("check_provider_model_catalog_task")


@celery_app.task
def check_provider_model_catalog_task() -> None:
    """Weekly check: diff each provider's live model list against what we curate."""
    publisher = NatsEventPublisher()
    for adapter in PROVIDER_REGISTRY.values():
        _check_adapter(adapter, publisher)


def _check_adapter(adapter: BaseProviderAdapter, publisher: NatsEventPublisher) -> None:
    try:
        live_models = adapter.fetch_live_model_ids()
    except Exception:
        logger.exception(
            "Failed to fetch live model list for provider '%s' — skipping this run",
            adapter.provider_id,
        )
        return

    curated_ids = {model.id for model in adapter.list_models()}
    diff = diff_provider_models(curated_ids, live_models, adapter.model_id_prefixes)

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
