"""Command to update a knowledge document, re-indexing only when content changed."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.knowledge_document import KnowledgeDocument
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.schemas.knowledge_document import KnowledgeDocumentUpdate
from app.services.knowledge.frontmatter import split_frontmatter
from app.tasks.index_knowledge_document import index_knowledge_document_task


class UpdateKnowledgeDocumentCommand:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = KnowledgeDocumentRepository(db)

    def execute(
        self, record: KnowledgeDocument, data: KnowledgeDocumentUpdate
    ) -> KnowledgeDocument:
        content_changed = data.raw_content is not None
        metadata, body = (
            split_frontmatter(data.raw_content) if content_changed else (None, None)
        )
        updated = self.repo.update(
            record, title=data.title, content=body, metadata=metadata
        )
        # A title-only update doesn't touch the embedded content, so it
        # doesn't need to re-chunk/re-embed. Only enqueue when raw_content
        # was actually part of the payload, and only after the commit above.
        if content_changed:
            index_knowledge_document_task.delay(str(updated.id))
        return updated
