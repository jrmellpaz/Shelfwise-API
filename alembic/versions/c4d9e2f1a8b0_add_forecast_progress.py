"""add forecast progress step fields

Revision ID: c4d9e2f1a8b0
Revises: b3c8d1e2f4a5
Create Date: 2026-03-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4d9e2f1a8b0"
down_revision: Union[str, None] = "b3c8d1e2f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("forecasts", sa.Column("progress_step", sa.Integer(), nullable=True))
    op.add_column("forecasts", sa.Column("progress_total", sa.Integer(), nullable=True))
    op.add_column("forecasts", sa.Column("progress_label", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("forecasts", "progress_label")
    op.drop_column("forecasts", "progress_total")
    op.drop_column("forecasts", "progress_step")
