# Import celery app first
from app.infra.celery_app import celery_app

# Initialize logging configuration for Celery workers
from app.infra.logging_config import LoggingConfig
from app.tasks.check_provider_model_catalog import check_provider_model_catalog_task
from app.tasks.index_knowledge_document import index_knowledge_document_task
from app.tasks.log_completion_usage import log_completion_usage

LoggingConfig()  # Initialize logging

__all__ = [
    "celery_app",
    "check_provider_model_catalog_task",
    "index_knowledge_document_task",
    "log_completion_usage",
]
