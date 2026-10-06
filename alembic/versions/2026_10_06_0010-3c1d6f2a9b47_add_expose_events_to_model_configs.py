"""add expose_events to model_configs

Revision ID: 3c1d6f2a9b47
Revises: 0ee07689f32a
Create Date: 2026-10-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c1d6f2a9b47"
down_revision: str | None = "0ee07689f32a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "model_configs",
        sa.Column(
            "expose_events",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("model_configs", "expose_events")
