from uuid import UUID

from app.db import SessionLocal
from app.inference.adapters.registry import get_adapter
from app.infra.celery_app import celery_app
from app.infra.logging_config import get_logger
from app.models.knowledge_chunk import KnowledgeChunk
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.embedding_config_params import EmbeddingConfigParams
from app.services.knowledge.chunking import chunk_text

logger = get_logger("index_knowledge_document")


@celery_app.task
def index_knowledge_document_task(document_id: str) -> None:
    """Chunk and embed a knowledge document using the default embedding
    ModelConfig. On a reindex, replacement embeddings are generated before
    existing chunks are replaced transactionally — no incremental diffing.

    Raises (rather than silently skipping) when no default embedding config
    exists, so the failure is visible in Celery monitoring/logs instead of
    leaving a document permanently unindexed with no operator-visible error.
    """
    db = SessionLocal()
    try:
        doc_repo = KnowledgeDocumentRepository(db)
        document = doc_repo.get_by_id(UUID(document_id))
        if document is None:
            # Deleted before the task ran; nothing to index.
            return

        embedding_config = ModelConfigRepository(db).get_default_for_type("embedding")
        if embedding_config is None:
            raise RuntimeError(
                "No default 'embedding' ModelConfig is configured; cannot index "
                f"KnowledgeDocument '{document_id}'"
            )

        params = EmbeddingConfigParams.model_validate(embedding_config.params or {})
        chunks = chunk_text(
            document.content,
            chunk_size=params.chunk_size,
            chunk_overlap=params.chunk_overlap,
            strategy=params.strategy,
        )
        vectors: list[list[float]] = []
        if chunks:
            adapter = get_adapter(embedding_config.provider)
            vectors = adapter.create_embeddings(embedding_config.model, chunks)
            if len(vectors) != len(chunks):
                raise RuntimeError(
                    "Embedding provider returned "
                    f"{len(vectors)} vectors for {len(chunks)} chunks"
                )

        # Preserve the currently usable index until configuration validation,
        # chunking, and the external provider call have all succeeded. The
        # deletion and replacement insert commit as one transaction below.
        doc_repo.delete_chunks_for_document(document.id)
        chunk_params_snapshot = params.model_dump()
        for index, (text, vector) in enumerate(zip(chunks, vectors)):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=text,
                    embedding=vector,
                    embedding_config_id=embedding_config.id,
                    chunk_params=chunk_params_snapshot,
                )
            )
        db.commit()
    except Exception:
        logger.exception(f"Failed to index knowledge document {document_id}")
        db.rollback()
        raise
    finally:
        db.close()
