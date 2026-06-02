import uuid
from sqlalchemy import Column, ForeignKey, String, Integer, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db import Base
from app.models.mixins import TimestampMixin


class CompletionRequest(Base, TimestampMixin):
    __tablename__ = "completion_requests"
    __table_args__ = (Index("ix_completion_requests_project_id", "project_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String(255), nullable=False, index=True)
    project_id = Column(String(255), nullable=False, default="*")
    model_config_slug = Column(String(255), nullable=True)
    provider = Column(String(100), nullable=False)
    model = Column(String(255), nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    cost_estimate_usd = Column(Numeric(12, 8), nullable=False, default=0)
    finish_reason = Column(String(50), nullable=True)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
