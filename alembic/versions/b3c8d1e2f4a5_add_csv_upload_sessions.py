"""add csv_upload_sessions

Revision ID: b3c8d1e2f4a5
Revises: f26172890c3a
Create Date: 2026-03-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b3c8d1e2f4a5"
down_revision: Union[str, None] = "f26172890c3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "csv_upload_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("raw_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("column_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_csv_upload_sessions_user_id", "csv_upload_sessions", ["user_id"], unique=False)
    op.create_index("ix_csv_upload_sessions_expires_at", "csv_upload_sessions", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_csv_upload_sessions_expires_at", table_name="csv_upload_sessions")
    op.drop_index("ix_csv_upload_sessions_user_id", table_name="csv_upload_sessions")
    op.drop_table("csv_upload_sessions")
