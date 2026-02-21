"""
Alembic environment.

Uses the synchronous psycopg2 URL for migrations (standard Alembic pattern).
SQLModel metadata is imported so Alembic can auto-generate migrations from models.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the src/ package importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlmodel import SQLModel

# Import all models so their tables are registered in SQLModel.metadata
import civilengineer.db.models  # noqa: F401

from civilengineer.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# Override sqlalchemy.url from environment / settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
