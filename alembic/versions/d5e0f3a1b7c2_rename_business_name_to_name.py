"""rename_business_name_to_name

Revision ID: d5e0f3a1b7c2
Revises: c4d9e2f1a8b0
Create Date: 2026-03-26 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d5e0f3a1b7c2"
down_revision: Union[str, None] = "c4d9e2f1a8b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Set a default value for any existing NULL rows before making non-nullable
    op.execute("UPDATE users SET business_name = '' WHERE business_name IS NULL")
    # Rename column
    op.alter_column("users", "business_name", new_column_name="name")
    # Make non-nullable
    op.alter_column("users", "name", nullable=False)


def downgrade() -> None:
    op.alter_column("users", "name", nullable=True)
    op.alter_column("users", "name", new_column_name="business_name")
