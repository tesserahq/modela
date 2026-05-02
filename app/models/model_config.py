import uuid
from sqlalchemy import Column, String, Boolean, Integer, Float, Text, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db import Base
from app.models.mixins import TimestampMixin, SoftDeleteMixin


class ModelConfig(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "model_configs"
    __table_args__ = (
        Index(
            "uq_model_configs_slug",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    provider = Column(String(100), nullable=False)
    model = Column(String(255), nullable=False)
    system_prompt = Column(Text, nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    top_p = Column(Float, nullable=True)
    output_schema = Column(JSONB, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False, index=True)
