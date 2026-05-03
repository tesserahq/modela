"""Add model_configs and completion_requests tables

Revision ID: add_model_configs_v1
Revises: initialize_database
Create Date: 2026-05-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "add_model_configs_v1"
down_revision: Union[str, None] = "initialize_database"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column(
            "output_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_model_configs_slug",
        "model_configs",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_model_configs_is_default",
        "model_configs",
        ["is_default"],
    )
    op.create_index(
        "ix_model_configs_deleted_at",
        "model_configs",
        ["deleted_at"],
    )

    op.create_table(
        "completion_requests",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("'*'"),
        ),
        sa.Column("model_config_slug", sa.String(length=255), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "cost_estimate_usd",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("finish_reason", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_completion_requests_request_id",
        "completion_requests",
        ["request_id"],
    )
    op.create_index(
        "ix_completion_requests_project_id",
        "completion_requests",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_completion_requests_project_id", table_name="completion_requests")
    op.drop_index("ix_completion_requests_request_id", table_name="completion_requests")
    op.drop_table("completion_requests")

    op.drop_index("ix_model_configs_deleted_at", table_name="model_configs")
    op.drop_index("ix_model_configs_is_default", table_name="model_configs")
    op.drop_index("uq_model_configs_slug", table_name="model_configs")
    op.drop_table("model_configs")
