"""
tests/worker/test_suggestion_processor.py — Tests for the AI suggestion
worker's job-processing and retry logic.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.worker.suggestion_processor import process_job, reclaim_stale_jobs


@pytest.mark.asyncio
async def test_process_job_requeues_on_transient_failure_without_raising(
    db_session: AsyncSession, make_job
):
    """A translation-service failure should roll back, increment retry_count,
    and re-queue the job — without raising MissingGreenlet/InvalidRequestError
    from reading expired attributes after rollback(). Note: This test runs on
    SQLite and verifies the resulting job state (status, retry_count, error_message),
    not the MissingGreenlet failure mode, which requires Postgres/asyncpg semantics."""
    job = await make_job(retry_count=0)

    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"
    translation_service.translate_verses.side_effect = RuntimeError("LLM boom")

    # process_job fetches context via httpx before calling translate_verses;
    # patch httpx so we reach the translate_verses call and hit the failure there.
    import httpx

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "targetLanguageName": "Spanish",
                "contextVerses": [],
                "sourceVerses": [{"id": 1, "verse_number": 1, "text": "In the beginning"}],
            }

    async def _fake_post(self, *args, **kwargs):
        return _FakeResponse()

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post  # type: ignore[method-assign]
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post  # type: ignore[method-assign]

    await db_session.refresh(job)
    assert job.status == "queued"
    assert job.retry_count == 1
    assert "LLM boom" in job.error_message


@pytest.mark.asyncio
async def test_process_job_marks_failed_after_max_retries(
    db_session: AsyncSession, make_job
):
    from app.core.constants import MAX_JOB_RETRIES

    job = await make_job(retry_count=MAX_JOB_RETRIES)

    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"
    translation_service.translate_verses.side_effect = RuntimeError("LLM boom")

    import httpx

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "targetLanguageName": "Spanish",
                "contextVerses": [],
                "sourceVerses": [{"id": 1, "verse_number": 1, "text": "In the beginning"}],
            }

    async def _fake_post(self, *args, **kwargs):
        return _FakeResponse()

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post  # type: ignore[method-assign]
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post  # type: ignore[method-assign]

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.retry_count == MAX_JOB_RETRIES


@pytest.mark.asyncio
async def test_updated_at_changes_on_status_update(db_session, make_job):
    job = await make_job(status="queued")
    original_updated_at = job.updated_at

    await asyncio.sleep(1.01)  # SQLite/Postgres now() has ~1s resolution here
    job.status = "processing"
    await db_session.commit()
    await db_session.refresh(job)

    assert job.updated_at > original_updated_at


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_requeues_orphaned_processing_job(db_session, make_job):
    from app.core.constants import STALE_PROCESSING_TIMEOUT_MINUTES

    stale_job = await make_job(status="processing")
    fresh_job = await make_job(
        status="processing", dedup_key="ai_suggestion:2:1:MAT:1:1:1"
    )

    # Backdate the stale job's updated_at past the timeout; leave fresh_job alone.
    stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        minutes=STALE_PROCESSING_TIMEOUT_MINUTES + 1
    )
    await db_session.execute(
        update(Job).where(Job.id == stale_job.id).values(updated_at=stale_cutoff)
    )
    await db_session.commit()

    reclaimed_count = await reclaim_stale_jobs(db_session)

    await db_session.refresh(stale_job)
    await db_session.refresh(fresh_job)
    assert reclaimed_count == 1
    assert stale_job.status == "queued"
    assert fresh_job.status == "processing"


@pytest.mark.asyncio
async def test_process_job_fails_immediately_on_4xx_from_fluent_api(
    db_session, make_job
):
    """A 404/400 from fluent-api's context endpoint can't be fixed by
    retrying — the job should go straight to 'failed' on the first attempt."""
    job = await make_job(retry_count=0)
    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"

    class _FakeResponse:
        status_code = 404

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "Not Found", request=httpx.Request("POST", "http://x"), response=self
            )

    async def _fake_post(self, *args, **kwargs):
        return _FakeResponse()

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.retry_count == 0  # never incremented — failed on first attempt


@pytest.mark.asyncio
async def test_process_job_skips_malformed_verse_id_instead_of_failing_job(
    db_session, make_job
):
    """One hallucinated/malformed verse_id from the LLM shouldn't fail the
    whole job — it should be logged and skipped, and the rest still saved."""
    job = await make_job(retry_count=0)

    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"
    translation_service.settings.google_ai_model = "gemini-test"
    translation_service.translate_verses.return_value = SimpleNamespace(
        translations=[
            SimpleNamespace(verse_id="not-a-valid-id", target_text="bad"),
            SimpleNamespace(verse_id="MAT_1_1", target_text="good translation"),
        ]
    )

    import httpx

    posted_payloads = []

    class _FakeContextResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "targetLanguageName": "Spanish",
                "contextVerses": [],
                "sourceVerses": [{"id": 42, "verse_number": 1, "text": "In the beginning"}],
            }

    class _FakeResultsResponse:
        def raise_for_status(self):
            pass

    async def _fake_post(self, url, *args, **kwargs):
        if "context" in url:
            return _FakeContextResponse()
        posted_payloads.append(kwargs.get("json"))
        return _FakeResultsResponse()

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post

    await db_session.refresh(job)
    assert job.status == "completed"
    assert len(posted_payloads) == 1
    saved_items = posted_payloads[0]["items"]
    assert len(saved_items) == 1
    assert saved_items[0]["bibleTextId"] == 42
    assert saved_items[0]["suggestedText"] == "good translation"


@pytest.mark.asyncio
async def test_process_job_skips_non_string_verse_id_instead_of_crashing(
    db_session, make_job
):
    """A verse_id that is None (or otherwise non-string) from the LLM must
    not crash the omission-summary block's guard clause — which previously
    called .rsplit() on item.verse_id unconditionally and raised an
    uncaught AttributeError, failing/requeuing the whole job."""
    job = await make_job(retry_count=0)

    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"
    translation_service.settings.google_ai_model = "gemini-test"
    translation_service.translate_verses.return_value = SimpleNamespace(
        translations=[
            SimpleNamespace(verse_id=None, target_text="bad"),
            SimpleNamespace(verse_id="MAT_1_1", target_text="good translation"),
        ]
    )

    import httpx

    posted_payloads = []

    class _FakeContextResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "targetLanguageName": "Spanish",
                "contextVerses": [],
                "sourceVerses": [{"id": 42, "verse_number": 1, "text": "In the beginning"}],
            }

    class _FakeResultsResponse:
        def raise_for_status(self):
            pass

    async def _fake_post(self, url, *args, **kwargs):
        if "context" in url:
            return _FakeContextResponse()
        posted_payloads.append(kwargs.get("json"))
        return _FakeResultsResponse()

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post

    await db_session.refresh(job)
    assert job.status == "completed"
    assert len(posted_payloads) == 1
    saved_items = posted_payloads[0]["items"]
    assert len(saved_items) == 1
    assert saved_items[0]["bibleTextId"] == 42
    assert saved_items[0]["suggestedText"] == "good translation"


@pytest.mark.asyncio
async def test_process_job_reuses_single_httpx_client(db_session, make_job):
    """The worker should open exactly one httpx.AsyncClient per job, not
    one per HTTP call."""
    job = await make_job(retry_count=0)
    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"
    translation_service.settings.google_ai_model = "gemini-test"
    translation_service.translate_verses.return_value = SimpleNamespace(
        translations=[SimpleNamespace(verse_id="MAT_1_1", target_text="hola")]
    )

    class _FakeContextResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "targetLanguageName": "Spanish",
                "contextVerses": [],
                "sourceVerses": [{"id": 42, "verse_number": 1, "text": "In the beginning"}],
            }

    class _FakeResultsResponse:
        def raise_for_status(self):
            pass

    async def _fake_post(self, url, *args, **kwargs):
        return _FakeContextResponse() if "context" in url else _FakeResultsResponse()

    init_count = 0
    orig_init = httpx.AsyncClient.__init__

    def _counting_init(self, *args, **kwargs):
        nonlocal init_count
        init_count += 1
        return orig_init(self, *args, **kwargs)

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post
    httpx.AsyncClient.__init__ = _counting_init
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post
        httpx.AsyncClient.__init__ = orig_init

    assert init_count == 1


@pytest.mark.asyncio
async def test_job_status_accepts_all_four_valid_values(db_session, make_job):
    for status in ("queued", "processing", "completed", "failed"):
        job = await make_job(status=status, dedup_key=f"ai_suggestion:test:{status}")
        assert job.status == status
