# pyright: reportMissingTypeStubs=false
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery("modela-worker")

celery_app.conf.update(
    broker_url=f"redis://{settings.redis_host}:{settings.redis_port}/0",
    result_backend=f"redis://{settings.redis_host}:{settings.redis_port}/0",
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
)

celery_app.autodiscover_tasks(["app.tasks"])  # ensure tasks are registered explicitly


_update_prices = None

from celery.signals import worker_init, worker_shutdown  # noqa: E402


@worker_init.connect
def _on_worker_init(sender, **kwargs):
    global _update_prices
    if _update_prices is not None:
        return
    from genai_prices import UpdatePrices

    _update_prices = UpdatePrices()
    _update_prices.start()


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
#         from app.tasks.process_import_items import process_import_items  # noqa: F401
#         from app.tasks.backfill_digests import backfill_digests_task  # noqa: F401
#         print(f"✅ Tasks registered: process_import_items, backfill_digests_task")
#     except ImportError as e:
#         print(f"⚠️  Warning: Could not import tasks: {e}")

# # Register tasks when this module is imported
# register_tasks()
