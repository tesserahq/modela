"""model_config: replace system_prompt text with system_prompt_id FK

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("model_configs", "system_prompt")
    op.add_column(
        "model_configs",
        sa.Column(
            "system_prompt_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_model_configs_system_prompt_id",
        "model_configs",
        "system_prompts",
        ["system_prompt_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_model_configs_system_prompt_id",
        "model_configs",
        type_="foreignkey",
    )
    op.drop_column("model_configs", "system_prompt_id")
    op.add_column(
        "model_configs",
        sa.Column("system_prompt", sa.Text(), nullable=True),
    )
