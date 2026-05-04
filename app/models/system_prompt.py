import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db import Base
from app.models.mixins import TimestampMixin


class SystemPromptVersion(Base):
    __tablename__ = "system_prompt_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_prompt_id = Column(
        UUID(as_uuid=True),
        ForeignKey("system_prompts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    version_number = Column(Integer, nullable=False)
    note = Column(String(512), nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class SystemPrompt(Base, TimestampMixin):
    __tablename__ = "system_prompts"
    __table_args__ = (Index("ix_system_prompts_name", "name", unique=True),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), nullable=False)
    current_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "system_prompt_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_system_prompts_current_version_id",
        ),
        nullable=True,
    )
