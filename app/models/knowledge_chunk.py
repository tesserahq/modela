"""Knowledge base chunk model — one embedded slice of a KnowledgeDocument."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db import Base


class KnowledgeChunk(Base):
    """A chunk is delete+recreate, never mutated in place, so it carries only
    created_at (no TimestampMixin/updated_at)."""

    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    # No declared dimension — see the migration comment and PRD 0019's
    # "Vector schema: undeclared dimension, no ANN index" for the rationale.
    embedding = Column(Vector(), nullable=False)
    embedding_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chunk_params = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    document = relationship("KnowledgeDocument", back_populates="chunks")
