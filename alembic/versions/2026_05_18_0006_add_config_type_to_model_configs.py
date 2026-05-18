"""add config_type to model_configs

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("config_type", sa.String(length=50), nullable=True),
    )
    op.execute(
        "UPDATE model_configs SET config_type = 'chat' WHERE config_type IS NULL"
    )
    op.alter_column("model_configs", "config_type", nullable=False)

    op.create_index(
        "uq_model_configs_default_per_type",
        "model_configs",
        ["config_type"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_configs_default_per_type", table_name="model_configs")
    op.drop_column("model_configs", "config_type")
