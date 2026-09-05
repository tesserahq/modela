"""Knowledge base document model."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import column_property, relationship

from app.db import Base
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.mixins import TimestampMixin


class KnowledgeDocument(Base, TimestampMixin):
    """A product-wide knowledge base document. Hard-deleted (no SoftDeleteMixin):
    there is no restore/versioning requirement, and retaining deleted embeddings
    would grow storage unbounded for no benefit."""

    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    # "metadata" is reserved on Base; alias it like MCPServer.extended_info does.
    extended_info = Column("metadata", JSONB, nullable=True)

    chunks = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Read-only, computed via a correlated subquery on every load — not a stored
    # column, so no migration and no separate count query per row (works for
    # both get_by_id and the paginated list_query()).
    chunk_count = column_property(
        select(func.count(KnowledgeChunk.id))
        .where(KnowledgeChunk.document_id == id)
        .correlate_except(KnowledgeChunk)
        .scalar_subquery()
    )
