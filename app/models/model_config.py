import uuid
from sqlalchemy import (
    Column,
    DateTime,
    String,
    Boolean,
    Integer,
    Float,
    Index,
    ForeignKey,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db import Base
from app.models.mixins import TimestampMixin, SoftDeleteMixin

model_config_mcp_servers = Table(
    "model_config_mcp_servers",
    Base.metadata,
    Column(
        "model_config_id",
        UUID(as_uuid=True),
        ForeignKey("model_configs.id"),
        primary_key=True,
    ),
    Column(
        "mcp_server_id",
        UUID(as_uuid=True),
        ForeignKey("mcp_servers.id"),
        primary_key=True,
    ),
    Column("created_at", DateTime(), nullable=False, server_default=text("now()")),
)


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
    system_prompt_id = Column(
        UUID(as_uuid=True),
        ForeignKey("system_prompts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    top_p = Column(Float, nullable=True)
    output_schema = Column(JSONB, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False, index=True)
    max_tool_rounds = Column(Integer, nullable=True)

    mcp_servers = relationship(
        "MCPServer",
        secondary=model_config_mcp_servers,
        lazy="select",
    )
