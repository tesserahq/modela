"""Query-time retrieval for the knowledge base — backs the search_knowledge_base
built-in tool. See PRD 0019 "Retrieval freshness filtering" and
"`search_knowledge_base` tool"."""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.inference.adapters.registry import get_adapter
from app.infra.logging_config import get_logger
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.repositories.model_config_repository import ModelConfigRepository

logger = get_logger("knowledge_search")

DEFAULT_TOP_K = 5
MAX_TOP_K = 20  # PRD 0019: capped even if top_k later becomes caller-configurable


def _freshness_filter():
    """Excludes chunks whose parent document is stale: status == "stale" or
    stale_after is in the past. Absent fields are always fresh (NULL-safe:
    a plain `!=`/`<` against a possibly-NULL JSONB field would silently drop
    rows that never set the field at all, since SQL's NULL comparisons are
    neither true nor false)."""
    status = KnowledgeDocument.extended_info["status"].astext
    stale_after = KnowledgeDocument.extended_info["stale_after"].astext
    today_iso = datetime.now(UTC).date().isoformat()
    return and_(
        or_(status.is_(None), status != "stale"),
        or_(stale_after.is_(None), stale_after >= today_iso),
    )


def search_knowledge_base_chunks(
    db: Session, query: str, top_k: int = DEFAULT_TOP_K
) -> list[str]:
    """Embed `query` with the active embedding ModelConfig and return the
    top-k (capped at MAX_TOP_K) most relevant, non-stale chunk contents.

    Returns [] rather than raising when no default embedding config exists or
    no documents are indexed — a live completion request shouldn't crash
    because retrieval found nothing; the missing-config failure is already
    surfaced loudly at indexing time (see app/tasks/index_knowledge_document.py)."""
    embedding_config = ModelConfigRepository(db).get_default_for_type("embedding")
    if embedding_config is None:
        logger.warning(
            "No default 'embedding' ModelConfig configured; search_knowledge_base "
            "returning no results"
        )
        return []

    adapter = get_adapter(embedding_config.provider)
    query_vector = adapter.create_embeddings(embedding_config.model, [query])[0]

    stmt = (
        select(KnowledgeChunk)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .filter(KnowledgeChunk.embedding_config_id == embedding_config.id)
        .filter(_freshness_filter())
        .order_by(KnowledgeChunk.embedding.cosine_distance(query_vector))
        .limit(min(top_k, MAX_TOP_K))
    )
    chunks = db.scalars(stmt).all()
    return [chunk.content for chunk in chunks]
