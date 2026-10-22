"""
tests/test_suggestions_service.py — Tests for enqueue_suggestion_jobs'
dedup-aware response reporting.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import JSON, MetaData, Text, VARCHAR, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.schemas.suggestions import SuggestionTriggerRequest
from app.models.job import Job
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
            "now",
            0,
            lambda: datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )

    async with engine.begin() as conn:
        await conn.run_sync(scratch_metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
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

    dumped = req.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {
        "projectUnitId": 1,
        "bibleId": 2,
        "bookCode": "MAT",
        "chapterNumber": 3,
        "verseStart": 4,
        "verseEnd": 5,
    }


def test_suggestion_trigger_request_rejects_inverted_verse_range():
    from pydantic import ValidationError

    from app.schemas.suggestions import SuggestionTriggerRequest

    with pytest.raises(ValidationError):
        SuggestionTriggerRequest.model_validate(
            {
                "projectUnitId": 1,
                "bibleId": 1,
                "bookCode": "MAT",
                "chapterNumber": 1,
                "verseStart": 5,
                "verseEnd": 1,
            }
        )


def test_suggestion_trigger_request_accepts_equal_verse_start_and_end():
    from app.schemas.suggestions import SuggestionTriggerRequest

    req = SuggestionTriggerRequest.model_validate(
        {
            "projectUnitId": 1,
            "bibleId": 1,
            "bookCode": "MAT",
            "chapterNumber": 1,
            "verseStart": 5,
            "verseEnd": 5,
        }
    )
    assert req.verse_start == req.verse_end == 5


def test_suggestion_trigger_request_rejects_book_code_with_separator_char():
    from pydantic import ValidationError

    from app.schemas.suggestions import SuggestionTriggerRequest

    with pytest.raises(ValidationError):
        SuggestionTriggerRequest.model_validate(
            {
                "projectUnitId": 1,
                "bibleId": 1,
                "bookCode": "MAT:1",
                "chapterNumber": 1,
                "verseStart": 1,
                "verseEnd": 1,
            }
        )


def test_suggestion_trigger_request_accepts_normal_book_code():
    from app.schemas.suggestions import SuggestionTriggerRequest

    req = SuggestionTriggerRequest.model_validate(
        {
            "projectUnitId": 1,
            "bibleId": 1,
            "bookCode": "MAT",
            "chapterNumber": 1,
            "verseStart": 1,
            "verseEnd": 1,
        }
    )
    assert req.book_code == "MAT"


@pytest.mark.parametrize("number", ["", "  ", "x" * 101])
def test_trigger_rejects_invalid_pericope_number(number):
    with pytest.raises(ValidationError):
        SuggestionTriggerRequest.model_validate(
            {**_request().model_dump(), "pericopeNumber": number, "pericopeSetId": 7}
        )


def test_trigger_strips_pericope_number():
    request = SuggestionTriggerRequest.model_validate(
        {
            **_request().model_dump(by_alias=True, exclude_none=True),
            "pericopeNumber": " 1_4a ",
            "pericopeSetId": 7,
        }
    )

    assert request.pericope_number == "1_4a"


@pytest.mark.parametrize(
    "heading_identity",
    [
        {"pericopeNumber": "1_4a"},
        {"pericopeSetId": 7},
        {"pericopeNumber": "1_4a", "pericopeSetId": None},
        {"pericopeNumber": None, "pericopeSetId": 7},
    ],
)
def test_trigger_rejects_incomplete_heading_identity(heading_identity):
    with pytest.raises(ValidationError, match="must be provided together"):
        SuggestionTriggerRequest.model_validate(
            {
                **_request().model_dump(by_alias=True, exclude_none=True),
                **heading_identity,
            }
        )


async def test_heading_jobs_keep_separate_dedup_identity_and_persist_metadata(
    db_session,
):
    verse_request = _request()
    heading_request = SuggestionTriggerRequest.model_validate(
        {
            **verse_request.model_dump(by_alias=True, exclude_none=True),
            "pericopeNumber": "1_4a",
            "pericopeSetId": 7,
        }
    )
    changed_range = heading_request.model_copy(update={"verse_end": 2})
    changed_pericope = heading_request.model_copy(update={"pericope_number": "1_4b"})
    changed_set = heading_request.model_copy(update={"pericope_set_id": 8})

    response = await enqueue_suggestion_jobs(
        db_session,
        [
            verse_request,
            heading_request,
            heading_request,
            changed_range,
            changed_pericope,
            changed_set,
        ],
    )

    assert response.message == "Queued 5 of 6 jobs (1 duplicate skipped)"
    jobs = (await db_session.execute(select(Job).order_by(Job.id))).scalars().all()
    assert jobs[0].dedup_key == "ai_suggestion:1:1:MAT:1:1:1"
    assert jobs[0].payload == verse_request.model_dump(by_alias=True, exclude_none=True)
    assert "pericopeNumber" not in jobs[0].payload
    for job in jobs[1:]:
        assert job.dedup_key.startswith("ai_suggestion:heading:")
        assert len(job.dedup_key) <= 255
    assert jobs[1].payload["pericopeNumber"] == "1_4a"
    assert jobs[1].payload["pericopeSetId"] == 7


async def _set_status(db_session, verse_start: int, **values) -> None:
    job = (
        await db_session.execute(
            select(Job).where(
                Job.dedup_key == f"ai_suggestion:1:1:MAT:1:{verse_start}:{verse_start}"
            )
        )
    ).scalar_one()
    for name, value in values.items():
        setattr(job, name, value)
    await db_session.commit()


async def _job(db_session, verse_start: int) -> Job:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(Job).where(
                Job.dedup_key == f"ai_suggestion:1:1:MAT:1:{verse_start}:{verse_start}"
            )
        )
    ).scalar_one()


async def test_retrigger_of_failed_job_requeues_it(db_session):
    await enqueue_suggestion_jobs(db_session, [_request(1)])
    await _set_status(
        db_session,
        1,
        status="failed",
        retry_count=3,
        error_message="Permanently failed after 3 retries: 402 RESOURCE_EXHAUSTED",
    )

    response = await enqueue_suggestion_jobs(db_session, [_request(1)])

    assert (response.queued, response.requeued, response.skipped) == (0, 1, 0)
    job = await _job(db_session, 1)
    assert job.status == "queued"
    assert job.retry_count == 0
    assert job.error_message is None
    assert job.payload == _request(1).model_dump(by_alias=True, exclude_none=True)


@pytest.mark.parametrize("status", ["queued", "processing", "completed"])
async def test_retrigger_of_unfailed_job_is_skipped_untouched(db_session, status):
    await enqueue_suggestion_jobs(db_session, [_request(1)])
    await _set_status(
        db_session, 1, status=status, retry_count=2, error_message="Retry 2/3: boom"
    )

    response = await enqueue_suggestion_jobs(db_session, [_request(1)])

    assert (response.queued, response.requeued, response.skipped) == (0, 0, 1)
    job = await _job(db_session, 1)
    assert job.status == status
    assert job.retry_count == 2
    assert job.error_message == "Retry 2/3: boom"


async def test_mixed_batch_reports_each_bucket(db_session):
    await enqueue_suggestion_jobs(db_session, [_request(1), _request(2), _request(3)])
    await _set_status(db_session, 1, status="failed", retry_count=3)
    await _set_status(db_session, 2, status="failed", retry_count=3)
    await _set_status(db_session, 3, status="completed")

    requests = [_request(1), _request(2), _request(3), _request(4)]
    response = await enqueue_suggestion_jobs(db_session, requests)

    assert (response.queued, response.requeued, response.skipped) == (1, 2, 1)
    assert response.queued + response.requeued + response.skipped == len(requests)
    assert response.message == (
        "Queued 1 of 4 jobs (2 failed jobs requeued, 1 duplicate skipped)"
    )
