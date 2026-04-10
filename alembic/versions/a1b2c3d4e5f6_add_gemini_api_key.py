"""Add gemini_api_key columns to users

Revision ID: a1b2c3d4e5f6
Revises: f7a2b3c4d5e6
Create Date: 2026-04-09 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str = "f7a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("gemini_api_key", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("gemini_api_key_added_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "gemini_api_key_added_at")
    op.drop_column("users", "gemini_api_key")
