"""
tests/worker/conftest.py — Real (in-memory SQLite) AsyncSession fixture
for testing app.worker.suggestion_processor against actual SQLAlchemy
commit/rollback/attribute-expiry behavior, instead of mocking the session.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import JSON, MetaData, Text, VARCHAR, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.job import Job


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A real AsyncSession backed by in-memory SQLite.

    expire_on_commit=False matches the production AsyncSessionLocal config
    (src/app/database.py).

    PostgreSQL-specific types (JSONB, ARRAY, UUID) are patched to
    SQLite-compatible equivalents. This is done on a clone of Job's table,
    built via Table.to_metadata() into a fixture-local MetaData, so that we
    never mutate Job.__table__ / the shared OwnedBase.metadata singleton
    (which is imported by Alembic and the production app) — mutating those
    in place would leak SQLite-specific types into the rest of the test
    process.

    The clone keeps the "ai" schema (matching Job.__table__) because the ORM
    still emits INSERT/SELECT statements against Job.__table__, which is
    schema-qualified; schema_translate_map below rewrites "ai" to no schema
    for both the clone's CREATE TABLE and the ORM's DML at execution time,
    since SQLite has no schema support.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})

    # Clone the Job table into a fixture-local MetaData and patch the clone's
    # PostgreSQL-specific column types to SQLite-compatible equivalents.
    scratch_metadata = MetaData()
    job_table = Job.__table__.to_metadata(scratch_metadata)
    for col in job_table.columns:
        if isinstance(col.type, JSONB):
            col.type = JSON()
        elif isinstance(col.type, ARRAY):
            # ARRAY becomes TEXT in SQLite. Job has no ARRAY columns today;
            # this branch is defensive for future models reusing this fixture.
            col.type = Text()
        elif isinstance(col.type, UUID):
            # UUID becomes VARCHAR(36) in SQLite. Job has no UUID columns
            # today; this branch is defensive for future models reusing
            # this fixture.
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
