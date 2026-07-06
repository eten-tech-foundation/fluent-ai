"""
tests/worker/test_suggestion_processor.py — Tests for the AI suggestion
worker's job-processing and retry logic.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.worker.suggestion_processor import process_job


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
    httpx.AsyncClient.post = _fake_post
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post

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
    httpx.AsyncClient.post = _fake_post
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.retry_count == MAX_JOB_RETRIES
