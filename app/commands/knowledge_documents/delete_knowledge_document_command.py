"""Command to hard-delete a knowledge document. Synchronous, no Celery involved —
the document_id FK's ON DELETE CASCADE removes its chunks in the same transaction."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.knowledge_document import KnowledgeDocument
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository


class DeleteKnowledgeDocumentCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = KnowledgeDocumentRepository(db)

    def execute(self, record: KnowledgeDocument) -> None:
        self.repo.delete(record)
