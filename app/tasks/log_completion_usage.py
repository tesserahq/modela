from typing import Optional
from app.infra.celery_app import celery_app
from app.infra.logging_config import get_logger
from app.db import SessionLocal

logger = get_logger("log_completion_usage")


@celery_app.task
def log_completion_usage(
    *,
    request_id: str,
    project_id: str,
    model_config_slug: str,
    provider: str,
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    finish_reason: Optional[str],
    latency_ms: Optional[int] = None,
    cost_estimate_usd: float = 0.0,
) -> None:
    db = SessionLocal()
    try:
        from app.repositories.completion_request_repository import (
            CompletionRequestRepository,
        )

        repo = CompletionRequestRepository(db)
        repo.create(
            {
                "request_id": request_id,
                "project_id": project_id,
                "model_config_slug": model_config_slug,
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "finish_reason": finish_reason,
                "latency_ms": latency_ms,
                "cost_estimate_usd": cost_estimate_usd,
            }
        )
    except Exception as exc:
        logger.error(f"Failed to log completion usage: {exc}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
