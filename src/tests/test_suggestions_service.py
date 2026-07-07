"""
tests/test_suggestions_service.py — Tests for enqueue_suggestion_jobs'
dedup-aware response reporting.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, MetaData, Text, VARCHAR, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.schemas.suggestions import SuggestionTriggerRequest
from app.services.suggestions import enqueue_suggestion_jobs


@pytest.fixture
async def db_session():
    from app.models.job import Job

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})

    # Clone Job table into a fixture-local MetaData and patch
    # PostgreSQL-specific column types to SQLite-compatible equivalents.
    scratch_metadata = MetaData()
    job_table = Job.__table__.to_metadata(scratch_metadata)
    for col in job_table.columns:
        if isinstance(col.type, JSONB):
            col.type = JSON()
        elif isinstance(col.type, ARRAY):
            col.type = Text()
        elif isinstance(col.type, UUID):
            col.type = VARCHAR(36)

    # Register PostgreSQL's now() function for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def register_now(dbapi_conn, connection_record) -> None:
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(scratch_metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _request(verse_start: int = 1) -> SuggestionTriggerRequest:
    return SuggestionTriggerRequest(
        projectUnitId=1,
        bibleId=1,
        bookCode="MAT",
        chapterNumber=1,
        verseStart=verse_start,
        verseEnd=verse_start,
    )


@pytest.mark.asyncio
async def test_enqueue_reports_actual_inserted_count_with_no_duplicates(db_session):
    response = await enqueue_suggestion_jobs(db_session, [_request(1), _request(2)])
    assert response.message == "Queued 2 jobs"


@pytest.mark.asyncio
async def test_enqueue_reports_duplicates_skipped(db_session):
    await enqueue_suggestion_jobs(db_session, [_request(1)])
    response = await enqueue_suggestion_jobs(db_session, [_request(1), _request(2)])
    assert response.message == "Queued 1 of 2 jobs (1 duplicate skipped)"


def test_suggestion_trigger_request_accepts_camelcase_and_exposes_snake_case():
    from app.schemas.suggestions import SuggestionTriggerRequest

    req = SuggestionTriggerRequest.model_validate(
        {
            "projectUnitId": 1,
            "bibleId": 2,
            "bookCode": "MAT",
            "chapterNumber": 3,
            "verseStart": 4,
            "verseEnd": 5,
        }
    )
    assert req.project_unit_id == 1
    assert req.bible_id == 2
    assert req.book_code == "MAT"
    assert req.chapter_number == 3
    assert req.verse_start == 4
    assert req.verse_end == 5

    dumped = req.model_dump(by_alias=True)
    assert dumped == {
        "projectUnitId": 1,
        "bibleId": 2,
        "bookCode": "MAT",
        "chapterNumber": 3,
        "verseStart": 4,
        "verseEnd": 5,
    }
