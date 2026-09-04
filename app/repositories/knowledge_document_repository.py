"""Repository for KnowledgeDocument CRUD. Hard-delete resource — not a
SoftDeleteRepository subclass, matching the system_prompts precedent."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument


class KnowledgeDocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, id: UUID) -> KnowledgeDocument | None:
        return (
            self.db.query(KnowledgeDocument).filter(KnowledgeDocument.id == id).first()
        )

    def list_query(self) -> Select:
        return select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())

    def create(
        self, *, title: str, content: str, metadata: dict[str, Any]
    ) -> KnowledgeDocument:
        record = KnowledgeDocument(title=title, content=content, extended_info=metadata)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def update(
        self,
        record: KnowledgeDocument,
        *,
        title: str | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeDocument:
        if title is not None:
            record.title = title
        if content is not None:
            record.content = content
            record.extended_info = metadata or {}
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete(self, record: KnowledgeDocument) -> None:
        """Hard delete. The document_id FK's ON DELETE CASCADE removes chunks."""
        self.db.delete(record)
        self.db.commit()

    def delete_chunks_for_document(self, document_id: UUID) -> None:
        """Used by the indexing task before re-chunking an updated document."""
        self.db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == document_id
        ).delete()
        self.db.commit()
