"""add knowledge base tables

Revision ID: eb85dec55f8f
Revises: 05b4752c7156
Create Date: 2026-09-04 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "eb85dec55f8f"
down_revision: Union[str, None] = "05b4752c7156"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "model_configs", sa.Column("params", postgresql.JSONB(), nullable=True)
    )

    op.create_table(
        "knowledge_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # No declared dimension: `Vector()` renders as bare `VECTOR` (no typmod),
        # letting rows produced by different embedding configs/dimensions coexist
        # in this column. Retrieval always scopes by embedding_config_id before
        # ranking, so mismatched dimensions are never compared. See PRD 0019
        # "Vector schema: undeclared dimension, no ANN index".
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedding_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_params", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_config_id"],
            ["model_configs.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_document_id",
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_config_id",
        "knowledge_chunks",
        ["embedding_config_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_knowledge_chunks_embedding_config_id", table_name="knowledge_chunks"
    )
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_column("model_configs", "params")
    # Deliberately not dropping the `vector` extension: other objects may come
    # to depend on it, and extension drop is a separate ops decision.
