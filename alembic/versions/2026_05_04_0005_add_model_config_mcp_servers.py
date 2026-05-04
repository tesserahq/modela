"""add model_config_mcp_servers join table and max_tool_rounds

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-05-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("max_tool_rounds", sa.Integer(), nullable=True),
    )

    op.create_table(
        "model_config_mcp_servers",
        sa.Column(
            "model_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_configs.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "mcp_server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_servers.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_model_config_mcp_servers_model_config_id",
        "model_config_mcp_servers",
        ["model_config_id"],
    )
    op.create_index(
        "ix_model_config_mcp_servers_mcp_server_id",
        "model_config_mcp_servers",
        ["mcp_server_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_config_mcp_servers_mcp_server_id",
        table_name="model_config_mcp_servers",
    )
    op.drop_index(
        "ix_model_config_mcp_servers_model_config_id",
        table_name="model_config_mcp_servers",
    )
    op.drop_table("model_config_mcp_servers")
    op.drop_column("model_configs", "max_tool_rounds")
