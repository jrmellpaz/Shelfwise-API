"""Drop unused 95% confidence interval columns.

Revision ID: h9c4d5e6f7a8
Revises: g8b3c4d5e6f7
Create Date: 2026-04-10

All models now use a hardcoded 80% confidence interval.
The 95% bound columns are no longer populated and can be removed.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h9c4d5e6f7a8"
down_revision = "g8b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("forecast_results", "lower_bound_95")
    op.drop_column("forecast_results", "upper_bound_95")


def downgrade() -> None:
    op.add_column(
        "forecast_results",
        sa.Column("upper_bound_95", sa.Float(), nullable=True),
    )
    op.add_column(
        "forecast_results",
        sa.Column("lower_bound_95", sa.Float(), nullable=True),
    )
