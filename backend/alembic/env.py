"""Alembic migration environment for SQLAlchemy AsyncORM."""

import asyncio
import os
import sys
from pathlib import Path
from logging.config import fileConfig

# psycopg async connections require a selector event loop on Windows.
if sys.platform.startswith("win"):
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is not None:
        asyncio.set_event_loop_policy(policy_cls())


from sqlalchemy import pool
from sqlalchemy.engine import Connection

from sqlalchemy.ext.asyncio import create_async_engine  # , AsyncEngine

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Ensure project root is on sys.path so db modules can be imported
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# Interpret the config file for Python logging.
# configure Python logging from file if logging sections exist; otherwise skip
try:
    fileConfig(config.config_file_name)
except KeyError:
    pass
# override sqlalchemy URL from environment if provided
try:
    from core.config import DATABASE_URL
except ImportError:
    DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Import your ORM's Base and models so Alembic can autogenerate
from db.base import Base  # noqa: E402
from db.session import make_async_database_url  # noqa: E402
import db.models  # noqa: E402, F401

target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection):
    """Run migrations in 'online' mode using a synchronous connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """Run migrations in 'online' mode using an AsyncEngine."""
    url = config.get_main_option("sqlalchemy.url")
    async_url = make_async_database_url(url) if url else None
    if not async_url:
        raise RuntimeError("Alembic requires a supported DATABASE_URL")

    connectable = create_async_engine(async_url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
