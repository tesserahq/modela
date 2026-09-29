"""Command to create a knowledge document and enqueue its indexing."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.knowledge_document import KnowledgeDocument
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.schemas.knowledge_document import KnowledgeDocumentCreate
from app.services.knowledge.frontmatter import split_frontmatter
from app.tasks.index_knowledge_document import index_knowledge_document_task
from app.db import on_commit


class CreateKnowledgeDocumentCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = KnowledgeDocumentRepository(db)

    def execute(self, data: KnowledgeDocumentCreate) -> KnowledgeDocument:
        metadata, body = split_frontmatter(data.raw_content)
        record = self.repo.create(title=data.title, content=body, metadata=metadata)
        # Enqueue only after the transaction commits, so the worker can never
        # pick up the task before the row is visible to its own DB session.
        document_id = str(record.id)
        on_commit(lambda: index_knowledge_document_task.delay(document_id))
        return record
