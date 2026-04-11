"""Add user location fields for weather-based forecasting.

Revision ID: g8b3c4d5e6f7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-10

Adds latitude, longitude, city, and country_name columns to the users
table so each user can have a weather location for forecast regressors.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "g8b3c4d5e6f7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("location_latitude", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("location_longitude", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("location_city", sa.String(), nullable=True))
    op.add_column(
        "users", sa.Column("location_country_name", sa.String(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "weather_enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "weather_enabled")
    op.drop_column("users", "location_country_name")
    op.drop_column("users", "location_city")
    op.drop_column("users", "location_longitude")
    op.drop_column("users", "location_latitude")
