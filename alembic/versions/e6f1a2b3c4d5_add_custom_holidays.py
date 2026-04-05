"""add custom_holidays table

Revision ID: e6f1a2b3c4d5
Revises: d5e0f3a1b7c2
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e6f1a2b3c4d5"
down_revision: Union[str, None] = "d5e0f3a1b7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_holidays",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_holidays_user_id", "custom_holidays", ["user_id"], unique=False)
    op.create_unique_constraint("uq_custom_holidays_user_date", "custom_holidays", ["user_id", "date"])


def downgrade() -> None:
    op.drop_constraint("uq_custom_holidays_user_date", "custom_holidays", type_="unique")
    op.drop_index("ix_custom_holidays_user_id", table_name="custom_holidays")
    op.drop_table("custom_holidays")
