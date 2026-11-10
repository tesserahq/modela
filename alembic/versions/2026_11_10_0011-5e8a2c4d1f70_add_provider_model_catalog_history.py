"""add provider model catalog history tables

Revision ID: 5e8a2c4d1f70
Revises: 3c1d6f2a9b47
Create Date: 2026-11-10 00:00:00.000000

Additive only (expand/contract rule in AGENTS.md): two new tables, no changes
to existing ones.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e8a2c4d1f70"
down_revision: str | None = "3c1d6f2a9b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "provider_model_catalog_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        sa.Column("error_category", sa.String(length=50), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_model_catalog_entries_provider_id"),
        "provider_model_catalog_entries",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_model_catalog_entries_kind"),
        "provider_model_catalog_entries",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_model_catalog_entries_detected_at"),
        "provider_model_catalog_entries",
        ["detected_at"],
        unique=False,
    )

    op.create_table(
        "provider_model_catalog_snapshots",
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("model_ids", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("provider_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("provider_model_catalog_snapshots")
    op.drop_index(
        op.f("ix_provider_model_catalog_entries_detected_at"),
        table_name="provider_model_catalog_entries",
    )
    op.drop_index(
        op.f("ix_provider_model_catalog_entries_kind"),
        table_name="provider_model_catalog_entries",
    )
    op.drop_index(
        op.f("ix_provider_model_catalog_entries_provider_id"),
        table_name="provider_model_catalog_entries",
    )
    op.drop_table("provider_model_catalog_entries")
