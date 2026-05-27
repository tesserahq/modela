"""add created_by_id to completion_requests

Revision ID: 05b4752c7156
Revises: e6f7a8b9c0d1
Create Date: 2026-05-27 13:19:27.910438

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "05b4752c7156"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "completion_requests", sa.Column("created_by_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_completion_requests_created_by_id",
        "completion_requests",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_completion_requests_created_by_id",
        "completion_requests",
        type_="foreignkey",
    )
    op.drop_column("completion_requests", "created_by_id")
