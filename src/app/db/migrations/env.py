"""Alembic environment for fluent-ai.

Restrictions enforced here:
  * target_metadata is OwnedBase.metadata only — there are no external models.
    The AI service has no SQL access to other schemas; API data is fetched
    over HTTP.
  * include_name filters out every schema except `ai`, so autogenerate
    cannot accidentally drop or alter objects this service does not own.
  * The alembic_version bookkeeping table lives in the `ai` schema so it is
    co-located with the objects it tracks and does not collide with any
    other service's migration history.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.db.base import OwnedBase  # noqa: F401 — imports model modules as side-effect

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _alembic_url() -> str:
    """Resolve the Alembic connection URL from the environment.

    Prefers MIGRATIONS_DATABASE_URL (DDL role), falls back to DATABASE_URL.
    Reads env vars directly instead of building the full Settings object, so
    migrations need only a DB URL — not unrelated app secrets like
    API_BASE_URL / API_SERVICE_KEY.
    """
    url = os.getenv("MIGRATIONS_DATABASE_URL") or os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# Inject the runtime URL so we never put credentials in alembic.ini.
config.set_main_option("sqlalchemy.url", _alembic_url())

target_metadata = OwnedBase.metadata


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """Restrict Alembic to the `ai` schema."""
    if type_ == "schema":
        return name == "ai"
    return True


def include_object(object_, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    """Belt-and-suspenders: skip any object outside the `ai` schema."""
    schema = getattr(object_, "schema", None)
    if schema is not None and schema != "ai":
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live DB)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,  # type: ignore[arg-type]
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="ai",
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,  # type: ignore[arg-type]
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="ai",
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
