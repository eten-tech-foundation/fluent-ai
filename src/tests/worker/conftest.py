"""
tests/worker/conftest.py — Real (in-memory SQLite) AsyncSession fixture
for testing app.worker.suggestion_processor against actual SQLAlchemy
commit/rollback/attribute-expiry behavior, instead of mocking the session.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import JSON, Text, VARCHAR, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import OwnedBase
from app.models.job import Job


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A real AsyncSession backed by in-memory SQLite.

    schema_translate_map maps the "ai" schema (Postgres-only concept) to
    no schema, since SQLite has no schema support. expire_on_commit=False
    matches the production AsyncSessionLocal config (src/app/database.py).

    PostgreSQL-specific types (JSONB, ARRAY, UUID) are patched to
    SQLite-compatible equivalents.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})

    # Only create the Job table; patch its PostgreSQL-specific column types
    # to SQLite-compatible equivalents.
    job_table = OwnedBase.metadata.tables["ai.jobs"]
    for col in job_table.columns:
        type_name = type(col.type).__name__
        if "JSONB" in type_name:
            col.type = JSON()
        elif "ARRAY" in type_name:
            # ARRAY becomes TEXT in SQLite
            col.type = Text()
        elif "UUID" in type_name:
            # UUID becomes VARCHAR(36) in SQLite
            col.type = VARCHAR(36)

    # Register PostgreSQL's now() function for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def register_now(dbapi_conn, connection_record):
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(timezone.utc).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: job_table.create(c, checkfirst=True))

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def make_job(db_session: AsyncSession):
    """Factory fixture: persist and return a Job row with sane defaults."""

    async def _make(**overrides) -> Job:
        defaults = {
            "task_type": "ai_suggestion",
            "payload": {
                "projectUnitId": 1,
                "bibleId": 1,
                "bookCode": "MAT",
                "chapterNumber": 1,
                "verseStart": 1,
                "verseEnd": 1,
            },
            "dedup_key": "ai_suggestion:1:1:MAT:1:1:1",
            "status": "queued",
            "retry_count": 0,
        }
        defaults.update(overrides)
        job = Job(**defaults)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)
        return job

    return _make
