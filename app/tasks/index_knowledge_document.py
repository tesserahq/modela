from uuid import UUID

from app.db import session_scope
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
    try:
        # Phase 1: read the document and the embedding configuration.
        with session_scope() as db:
            document = KnowledgeDocumentRepository(db).get_by_id(UUID(document_id))
            if document is None:
                # Deleted before the task ran; nothing to index.
                return
            content = document.content

            embedding_config = ModelConfigRepository(db).get_default_for_type(
                "embedding"
            )
            if embedding_config is None:
                raise RuntimeError(
                    "No default 'embedding' ModelConfig is configured; cannot index "
                    f"KnowledgeDocument '{document_id}'"
                )
            embedding_config_id = embedding_config.id
            provider = embedding_config.provider
            model = embedding_config.model
            params = EmbeddingConfigParams.model_validate(embedding_config.params or {})

        # Phase 2: chunk and embed, with no database transaction open.
        chunks = chunk_text(
            content,
            chunk_size=params.chunk_size,
            chunk_overlap=params.chunk_overlap,
            strategy=params.strategy,
        )
        vectors: list[list[float]] = []
        if chunks:
            vectors = get_adapter(provider).create_embeddings(model, chunks)
            if len(vectors) != len(chunks):
                raise RuntimeError(
                    "Embedding provider returned "
                    f"{len(vectors)} vectors for {len(chunks)} chunks"
                )

        # Phase 3: replace the chunks. The currently usable index is kept until
        # configuration validation, chunking and the provider call have all
        # succeeded; deletion and replacement commit as one transaction.
        with session_scope() as db:
            doc_repo = KnowledgeDocumentRepository(db)
            document = doc_repo.get_by_id(UUID(document_id))
            if document is None:
                # Deleted while embedding; nothing to store.
                return
            doc_repo.delete_chunks_for_document(document.id)
            chunk_params_snapshot = params.model_dump()
            for index, (text, vector) in enumerate(zip(chunks, vectors)):
                db.add(
                    KnowledgeChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=text,
                        embedding=vector,
                        embedding_config_id=embedding_config_id,
                        chunk_params=chunk_params_snapshot,
                    )
                )
    except Exception:
        logger.exception(f"Failed to index knowledge document {document_id}")
        raise
