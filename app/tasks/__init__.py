# Import celery app first
from app.core.celery_app import celery_app
from app.tasks.log_completion_usage import log_completion_usage

try:
    from app.tasks.process_nats_event import process_nats_event_task
except ImportError:
    process_nats_event_task = None  # type: ignore[assignment]

# Initialize logging configuration for Celery workers
from app.core.logging_config import LoggingConfig

LoggingConfig()  # Initialize logging

__all__ = ["celery_app", "log_completion_usage", "process_nats_event_task"]
