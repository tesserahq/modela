# pyright: reportMissingTypeStubs=false
from celery import Celery
from celery.schedules import crontab
from tessera_sdk.config import get_settings as get_sdk_settings

from app.config import get_settings

settings = get_settings()
redis_settings = get_sdk_settings()

celery_app = Celery("modela-worker")

celery_app.conf.update(
    broker_url=redis_settings.redis_connection_url,
    result_backend=redis_settings.redis_connection_url,
    task_default_queue="modela",  # Use dedicated queue for modela tasks
    task_routes={
        "app.tasks.*": {"queue": "modela"},  # Route all app.tasks.* to modela queue
    },
)

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Required for celery-exporter (listens to the Celery event bus on the
    # broker) to see this worker's tasks at all — without these, task events
    # are off by default and the exporter has nothing to report.
    worker_send_task_events=True,
    task_send_sent_event=True,
)

celery_app.autodiscover_tasks(["app.tasks"])  # ensure tasks are registered explicitly

# First beat schedule in this repo — requires the `modela-beat` deployment
# (already provisioned in production, running `celery ... beat`) to pick it up.
celery_app.conf.beat_schedule = {
    # Diffs each provider adapter's live model list against its curated
    # _models list and publishes a NATS event on drift. Runs weekly, Monday
    # 06:00 UTC.
    "check-provider-model-catalog-weekly": {
        "task": "app.tasks.check_provider_model_catalog.check_provider_model_catalog_task",
        "schedule": crontab(day_of_week=1, hour=6, minute=0),
    },
}


_update_prices = None

from celery.signals import (
    worker_init,
    worker_process_init,
    worker_shutdown,
)


@worker_init.connect
def _on_worker_init(sender, **kwargs):
    global _update_prices
    if _update_prices is not None:
        return
    from genai_prices import UpdatePrices

    _update_prices = UpdatePrices()
    _update_prices.start()


@worker_process_init.connect
def _on_worker_process_init(sender, **kwargs):
    # Fires once per (post-fork) worker child process, unlike worker_init which
    # runs pre-fork in the parent — the OTLP gRPC exporter connection is not
    # fork-safe, so tracing must be set up here.
    from app.infra.logging_config import get_logger

    logger = get_logger("celery_app")

    if not settings.otel_enabled:
        logger.info("OTel tracing disabled for worker (OTEL_ENABLED is not set)")
        return
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        from app.telemetry import setup_tracing

        tracer_provider = setup_tracing()
        CeleryInstrumentor().instrument(tracer_provider=tracer_provider)
        logger.info(
            "OTel tracing enabled for worker "
            f"(endpoint={settings.otel_exporter_otlp_endpoint}, "
            f"service={settings.otel_service_name})"
        )
    except Exception:
        logger.exception("Failed to set up OTel tracing for worker")


@worker_shutdown.connect
def _on_worker_shutdown(sender, **kwargs):
    global _update_prices
    if _update_prices is not None:
        _update_prices.stop()
        _update_prices = None


# # Explicitly register tasks to ensure they're available
# def register_tasks():
#     """Explicitly import tasks to ensure registration."""
#     try:
#         from app.tasks.process_import_items import process_import_items
#         from app.tasks.backfill_digests import backfill_digests_task
#         print(f"✅ Tasks registered: process_import_items, backfill_digests_task")
#     except ImportError as e:
#         print(f"⚠️  Warning: Could not import tasks: {e}")

# # Register tasks when this module is imported
# register_tasks()
