"""add upload session GET endpoint columns

Revision ID: f7a2b3c4d5e6
Revises: e6f1a2b3c4d5
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f7a2b3c4d5e6"
down_revision: Union[str, None] = "e6f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename 'stage' to 'status' for clarity
    op.alter_column(
        "csv_upload_sessions",
        "stage",
        new_column_name="status",
    )

    # Add new JSONB columns for persisting upload/validation data
    op.add_column(
        "csv_upload_sessions",
        sa.Column("columns_detected", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "csv_upload_sessions",
        sa.Column("suggested_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "csv_upload_sessions",
        sa.Column("confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "csv_upload_sessions",
        sa.Column("validation_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("csv_upload_sessions", "validation_result")
    op.drop_column("csv_upload_sessions", "confidence")
    op.drop_column("csv_upload_sessions", "suggested_mapping")
    op.drop_column("csv_upload_sessions", "columns_detected")

    op.alter_column(
        "csv_upload_sessions",
        "status",
        new_column_name="stage",
    )
