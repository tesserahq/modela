"""add enabled_tools to model_configs

Revision ID: 0ee07689f32a
Revises: eb85dec55f8f
Create Date: 2026-09-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0ee07689f32a"
down_revision: str | None = "eb85dec55f8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "model_configs",
        sa.Column("enabled_tools", postgresql.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("model_configs", "enabled_tools")
