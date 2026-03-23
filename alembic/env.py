"""
Alembic environment configuration.

Reads DATABASE_URL from app settings and imports all models
so that --autogenerate can detect schema changes.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, create_engine

from app.config import settings
from app.database import Base

# Import all models so Alembic can detect them for --autogenerate
from app.models import (  # noqa: F401
    activity_log,
    csv_upload_session,
    forecast,
    forecast_result,
    product,
    sales_data,
    user,
)

# Alembic Config object
config = context.config

# Setup loggers from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData for --autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an engine and connects to the database to apply migrations.
    Uses create_engine directly with app settings to avoid ConfigParser
    %-interpolation issues with URL-encoded passwords.
    """
    connectable = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
