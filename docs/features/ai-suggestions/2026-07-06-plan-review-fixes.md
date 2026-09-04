# AI Suggestions Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the reliability, correctness, and consistency issues raised in `AI_SUGGESTIONS_REVIEW.md` for the AI-suggestions background-job feature (fluent-ai repo, branch `draft/ai-suggestions`), without changing the external HTTP contract with fluent-api or the TS caller.

**Architecture:** The feature is a generic `ai.jobs` queue (Postgres, `FOR UPDATE SKIP LOCKED` claiming) drained by an asyncio worker loop (`app/worker/suggestion_processor.py`) that calls fluent-api over HTTP for context/results and Google Gemini for translation. Fixes are surgical edits to the worker, model, schema, and service layers — no new services or queues introduced.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 async ORM, asyncpg, Alembic, pytest + pytest-asyncio, httpx, google-genai SDK.

## Global Constraints

- Do not change the wire format of `/suggestions` (still accepts a JSON array of camelCase objects) or of the fluent-api calls (`/ai-suggestions/internal/context`, `/ai-suggestions/internal/results`) — both still send/receive camelCase JSON keys.
- `AsyncSessionLocal` is configured with `expire_on_commit=False` (`src/app/database.py:34`) — `commit()` does not expire ORM attributes here, but `rollback()` always does, regardless of that setting. Every fix must account for this.
- No new external services or queue technologies. Stay within the existing `ai` Postgres schema and the existing HTTP-only boundary to fluent-api.
- Test command: `uv run pytest src/tests -v`. Lint: `uv run ruff check src`. Type-check: `uv run mypy src`.
- Items #8 (idempotent results push) and #14 (`str(e)[:500]` sensitivity) from the review are **out of scope** for this plan: #8 requires a change in the separate `fluent-api` repo (its results endpoint must dedupe by `bibleTextId`+`projectUnitId`), and #14 is a flagged risk acceptable for this internal-only worker, not a required code change. Do not attempt either here.

---

## File Structure

| File | Change |
|---|---|
| `src/app/worker/suggestion_processor.py` | Fix rollback/expired-attribute bug, add stale-job reclaim, distinguish retryable vs. permanent errors, tolerate malformed per-item LLM output, reuse one `httpx.AsyncClient` |
| `src/app/models/job.py` | Add `onupdate=func.now()` to `updated_at` |
| `src/app/core/constants.py` | Add `STALE_PROCESSING_TIMEOUT_MINUTES`; remove unused `MAX_CONTEXT_VERSES_TOTAL` / `MAX_CONTEXT_VERSES_FTS` |
| `src/app/services/suggestions.py` | Report actual inserted row count instead of requested count; switch to snake_case attribute access |
| `src/app/schemas/suggestions.py` | Add `Field(alias=...)` + `populate_by_name=True` so Python attributes are snake_case while wire format stays camelCase |
| `src/app/api/v1/endpoints/translations.py` | Use the shared `GoogleGeminiDep` singleton instead of constructing a new client per request |
| `src/app/services/translation_service.py` | Pass a `response_schema` through to Gemini instead of manual fence-stripping |
| `src/app/core/ai_clients/google_gemini.py` | Add `response_schema` passthrough parameter |
| `src/app/config.py` | Reject insecure default secrets when `environment == "production"` |
| `src/tests/worker/conftest.py` | New — in-memory SQLite fixture (schema-translate-mapped) providing a real `AsyncSession` bound to a `Job` table, for realistic ORM-expiry testing |
| `src/tests/worker/test_suggestion_processor.py` | New — tests for rollback/retry, non-retryable errors, malformed LLM items, reclaim |
| `src/tests/test_suggestions_service.py` | New — tests for enqueue row-count reporting and snake_case access |
| `src/tests/test_config.py` | New — tests for the production-safety validator |
| `pyproject.toml` | Add `aiosqlite` to the `dev` dependency group (needed only for the new in-memory worker tests) |

---

## Task 1: Add `aiosqlite` test dependency and a real-session worker test fixture

Every worker test below needs a real SQLAlchemy `AsyncSession` (not a mock) so that `rollback()`'s attribute-expiry behavior is actually exercised — that's the whole point of review finding #1. This task sets up that fixture once so later tasks can just use it.

**Files:**
- Modify: `pyproject.toml`
- Create: `src/tests/worker/__init__.py`
- Create: `src/tests/worker/conftest.py`

**Interfaces:**
- Produces: pytest fixture `db_session` (async, yields a real `AsyncSession` bound to an in-memory SQLite engine with the `ai.jobs` table created) and a `make_job(**overrides) -> Job` helper that inserts and returns a persisted `Job` row.

- [ ] **Step 1: Add the dev dependency**

Edit `pyproject.toml`:
```toml
[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
    "aiosqlite>=0.20.0",
]
```

Run: `uv sync`
Expected: lockfile updates, `aiosqlite` installed into `.venv`.

- [ ] **Step 2: Create the test package init**

Create `src/tests/worker/__init__.py` (empty file).

- [ ] **Step 3: Write the fixture**

Create `src/tests/worker/conftest.py`:
```python
"""
tests/worker/conftest.py — Real (in-memory SQLite) AsyncSession fixture
for testing app.worker.suggestion_processor against actual SQLAlchemy
commit/rollback/attribute-expiry behavior, instead of mocking the session.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import OwnedBase
from app.models.job import Job


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A real AsyncSession backed by in-memory SQLite.

    schema_translate_map maps the "ai" schema (Postgres-only concept) to
    no schema, since SQLite has no schema support. expire_on_commit=False
    matches the production AsyncSessionLocal config (src/app/database.py).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})

    async with engine.begin() as conn:
        await conn.run_sync(OwnedBase.metadata.create_all)

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
```

- [ ] **Step 4: Verify the fixture works**

Create a throwaway smoke test to confirm the fixture is wired correctly (this file is deleted in Step 5, it's only to validate the fixture in isolation):

Create `src/tests/worker/test_fixture_smoke.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job


@pytest.mark.asyncio
async def test_make_job_persists_a_row(db_session: AsyncSession, make_job):
    job = await make_job()
    assert job.id is not None
    assert job.status == "queued"
    assert job.retry_count == 0
```

Run: `uv run pytest src/tests/worker/test_fixture_smoke.py -v`
Expected: `1 passed`

- [ ] **Step 5: Delete the smoke test and commit**

```bash
rm src/tests/worker/test_fixture_smoke.py
git add pyproject.toml uv.lock src/tests/worker/__init__.py src/tests/worker/conftest.py
git commit -m "test: add in-memory SQLite fixture for worker tests"
```

---

## Task 2: Fix expired-attribute access after `rollback()` (review #1)

**Files:**
- Modify: `src/app/worker/suggestion_processor.py:154-171`
- Test: `src/tests/worker/test_suggestion_processor.py` (new)

**Interfaces:**
- Consumes: `db_session` / `make_job` fixtures from Task 1.
- Produces: no interface change — `process_job(db, job, translation_service)` keeps its existing signature.

- [ ] **Step 1: Write the failing test**

Create `src/tests/worker/test_suggestion_processor.py`:
```python
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
    from reading expired attributes after rollback()."""
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
```

- [ ] **Step 2: Run the tests to see the current (buggy) behavior**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py -v`
Expected: both tests currently pass or fail inconsistently depending on SQLite's laxer expiry semantics vs. Postgres — note in the PR description that the *real* failure mode (`MissingGreenlet`) only reproduces reliably against Postgres/asyncpg, since SQLite via aiosqlite's greenlet handling differs slightly. Proceed with the fix regardless — it removes the unsafe pattern in all cases. If either test fails here, note the failure output before moving on.

- [ ] **Step 3: Fix the except block**

In `src/app/worker/suggestion_processor.py`, replace lines 154-171:
```python
    except Exception as e:
        logger.error(f"Error processing job {job.id}: {e}")
        await db.rollback()

        # Retry logic: re-queue if under the retry limit
        if job.retry_count < MAX_JOB_RETRIES:
            job.retry_count += 1
            job.status = "queued"
            job.error_message = f"Retry {job.retry_count}/{MAX_JOB_RETRIES}: {str(e)[:500]}"
            logger.info(
                f"Re-queuing job {job.id} (retry {job.retry_count}/{MAX_JOB_RETRIES})"
            )
        else:
            job.status = "failed"
            job.error_message = f"Permanently failed after {MAX_JOB_RETRIES} retries: {str(e)[:500]}"
            logger.error(f"Job {job.id} permanently failed after {MAX_JOB_RETRIES} retries.")

        await db.commit()
```
with:
```python
    except Exception as e:
        # Capture everything we need from `job` BEFORE rollback(): rollback()
        # expires all ORM attributes on this instance regardless of the
        # session's expire_on_commit setting, and reading an expired
        # attribute triggers an implicit lazy-load SELECT that raises
        # MissingGreenlet/InvalidRequestError under asyncio. Writes (below)
        # are safe post-rollback; reads are not.
        job_id = job.id
        current_retry_count = job.retry_count

        logger.error(f"Error processing job {job_id}: {e}")
        await db.rollback()

        # Retry logic: re-queue if under the retry limit
        if current_retry_count < MAX_JOB_RETRIES:
            new_retry_count = current_retry_count + 1
            job.retry_count = new_retry_count
            job.status = "queued"
            job.error_message = f"Retry {new_retry_count}/{MAX_JOB_RETRIES}: {str(e)[:500]}"
            logger.info(
                f"Re-queuing job {job_id} (retry {new_retry_count}/{MAX_JOB_RETRIES})"
            )
        else:
            job.status = "failed"
            job.error_message = f"Permanently failed after {MAX_JOB_RETRIES} retries: {str(e)[:500]}"
            logger.error(f"Job {job_id} permanently failed after {MAX_JOB_RETRIES} retries.")

        await db.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/app/worker/suggestion_processor.py src/tests/worker/test_suggestion_processor.py
git commit -m "fix: avoid reading expired job attributes after rollback in worker"
```

---

## Task 3: Add `onupdate` to `Job.updated_at` (review #5)

This must land before Task 4 (the stale-job reaper), which relies on `updated_at` moving whenever a job's status changes.

**Files:**
- Modify: `src/app/models/job.py`
- Test: `src/tests/worker/test_suggestion_processor.py` (append)

**Interfaces:**
- Produces: `Job.updated_at` now advances on every ORM-issued `UPDATE`, which Task 4's reclaim query depends on.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/worker/test_suggestion_processor.py`:
```python
import asyncio


@pytest.mark.asyncio
async def test_updated_at_changes_on_status_update(db_session, make_job):
    job = await make_job(status="queued")
    original_updated_at = job.updated_at

    await asyncio.sleep(1.01)  # SQLite/Postgres now() has ~1s resolution here
    job.status = "processing"
    await db_session.commit()
    await db_session.refresh(job)

    assert job.updated_at > original_updated_at
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_updated_at_changes_on_status_update -v`
Expected: FAIL — `assert job.updated_at > original_updated_at` fails because `updated_at` never moves past its insert-time default.

- [ ] **Step 3: Add `onupdate` to the model**

In `src/app/models/job.py`, find the import line for `text` and add `func`:
```python
from sqlalchemy import Index, UniqueConstraint, func, text
```
(adjust to match whatever the existing import line lists — add `func` alongside the other `sqlalchemy` imports already in the file).

Replace:
```python
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )
```
with:
```python
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()"), onupdate=func.now()
    )
```

`onupdate=func.now()` is a client-side SQLAlchemy behavior (it adds `now()` to the `SET` clause of any ORM-issued `UPDATE` for this row) — it does **not** change the table's DDL, so no Alembic migration is required for this change.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_updated_at_changes_on_status_update -v`
Expected: PASS

- [ ] **Step 5: Run the full worker test file to check for regressions**

Run: `uv run pytest src/tests/worker/ -v`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add src/app/models/job.py src/tests/worker/test_suggestion_processor.py
git commit -m "fix: bump Job.updated_at on every status transition"
```

---

## Task 4: Reclaim stale `processing` jobs (review #2)

**Files:**
- Modify: `src/app/core/constants.py`
- Modify: `src/app/worker/suggestion_processor.py`
- Test: `src/tests/worker/test_suggestion_processor.py` (append)

**Interfaces:**
- Consumes: `Job.updated_at` onupdate behavior from Task 3.
- Produces: `reclaim_stale_jobs(db: AsyncSession) -> int` — returns the number of rows reclaimed. Called from `worker_loop()` once per poll iteration, before the claim query.

- [ ] **Step 1: Add the timeout constant**

In `src/app/core/constants.py`, add below `MAX_JOB_RETRIES`:
```python
# How long (in minutes) a job may sit in 'processing' before it's considered
# orphaned (e.g. the worker that claimed it crashed mid-job) and reclaimed
# back to 'queued' by the next worker to poll.
STALE_PROCESSING_TIMEOUT_MINUTES = 15
```

- [ ] **Step 2: Write the failing test**

Append to `src/tests/worker/test_suggestion_processor.py`:
```python
from datetime import datetime, timedelta

from sqlalchemy import update

from app.models.job import Job
from app.worker.suggestion_processor import reclaim_stale_jobs


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_requeues_orphaned_processing_job(db_session, make_job):
    from app.core.constants import STALE_PROCESSING_TIMEOUT_MINUTES

    stale_job = await make_job(status="processing")
    fresh_job = await make_job(
        status="processing", dedup_key="ai_suggestion:2:1:MAT:1:1:1"
    )

    # Backdate the stale job's updated_at past the timeout; leave fresh_job alone.
    stale_cutoff = datetime.utcnow() - timedelta(
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_reclaim_stale_jobs_requeues_orphaned_processing_job -v`
Expected: FAIL — `ImportError: cannot import name 'reclaim_stale_jobs'`

- [ ] **Step 4: Implement `reclaim_stale_jobs` and wire it into the loop**

In `src/app/worker/suggestion_processor.py`, add imports (near the top, alongside the existing `sqlalchemy` import):
```python
from datetime import datetime, timedelta

from sqlalchemy import select, update
```
(replace the existing `from sqlalchemy import select` line with the combined `select, update` import).

Add the constant to the existing constants import block:
```python
from app.core.constants import (
    WORKER_POLL_INTERVAL_SECONDS,
    WORKER_MAX_CONSECUTIVE_FAILURES,
    MAX_JOB_RETRIES,
    STALE_PROCESSING_TIMEOUT_MINUTES,
)
```

Add a new function above `worker_loop`:
```python
async def reclaim_stale_jobs(db: AsyncSession) -> int:
    """Requeue jobs stuck in 'processing' longer than the stale timeout.

    Handles the case where a worker crashed or was killed mid-job: the row's
    FOR UPDATE lock is released the moment status flips to 'processing'
    (see process_job), so a crash after that point leaves the row orphaned
    with no lock and no worker watching it. This sweep runs once per poll
    cycle and requeues anything whose updated_at is older than the timeout.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_TIMEOUT_MINUTES)
    stmt = (
        update(Job)
        .where(Job.status == "processing", Job.updated_at < cutoff)
        .values(status="queued")
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount:
        logger.warning(f"Reclaimed {result.rowcount} stale 'processing' job(s).")
    return result.rowcount
```

In `worker_loop`, call it at the top of each iteration, before the claim query. Replace:
```python
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # ----------------------------------------------------------
                # H1 Fix: Use FOR UPDATE SKIP LOCKED to claim jobs safely.
                # This prevents two workers from picking the same job.
                # ----------------------------------------------------------
                query = (
```
with:
```python
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await reclaim_stale_jobs(db)

                # ----------------------------------------------------------
                # H1 Fix: Use FOR UPDATE SKIP LOCKED to claim jobs safely.
                # This prevents two workers from picking the same job.
                # ----------------------------------------------------------
                query = (
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_reclaim_stale_jobs_requeues_orphaned_processing_job -v`
Expected: PASS

- [ ] **Step 6: Run the full worker test file to check for regressions**

Run: `uv run pytest src/tests/worker/ -v`
Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add src/app/core/constants.py src/app/worker/suggestion_processor.py src/tests/worker/test_suggestion_processor.py
git commit -m "feat: reclaim jobs stuck in processing after a worker crash"
```

---

## Task 5: Distinguish retryable vs. permanent failures (review #3)

**Files:**
- Modify: `src/app/worker/suggestion_processor.py`
- Test: `src/tests/worker/test_suggestion_processor.py` (append)

**Interfaces:**
- Produces: `NonRetryableJobError(Exception)` — raised internally within `process_job` for failures that retrying cannot fix (4xx from fluent-api). Caught in the `except` block to skip straight to `status="failed"` regardless of `retry_count`.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/worker/test_suggestion_processor.py`:
```python
import httpx


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
```

Add `process_job` to the existing import line at the top of the file if not already imported (it already is from Task 2).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_fails_immediately_on_4xx_from_fluent_api -v`
Expected: FAIL — job ends up `status == "queued"` with `retry_count == 1` (current code retries everything identically).

- [ ] **Step 3: Add `NonRetryableJobError` and raise it for 4xx responses**

In `src/app/worker/suggestion_processor.py`, add near the top (after the logger is created):
```python
class NonRetryableJobError(Exception):
    """Raised for failures that retrying cannot fix (e.g. a 4xx from
    fluent-api, or a permanently malformed request payload). Jobs that
    raise this go straight to 'failed' without consuming retry attempts."""
```

Wrap both `raise_for_status()` call sites. Replace the first one (context fetch):
```python
            context_resp.raise_for_status()
```
with:
```python
            try:
                context_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NonRetryableJobError(
                        f"fluent-api rejected context request with "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
                raise
```

Replace the second one (results push):
```python
                save_resp.raise_for_status()
```
with:
```python
                try:
                    save_resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if 400 <= exc.response.status_code < 500:
                        raise NonRetryableJobError(
                            f"fluent-api rejected results push with "
                            f"{exc.response.status_code}: {exc}"
                        ) from exc
                    raise
```

- [ ] **Step 4: Skip the retry count check for non-retryable errors**

Replace the retry branch built in Task 2:
```python
        # Retry logic: re-queue if under the retry limit
        if current_retry_count < MAX_JOB_RETRIES:
```
with:
```python
        # Retry logic: re-queue if under the retry limit — unless this is a
        # permanent failure that retrying cannot fix.
        if not isinstance(e, NonRetryableJobError) and current_retry_count < MAX_JOB_RETRIES:
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_fails_immediately_on_4xx_from_fluent_api -v`
Expected: PASS

- [ ] **Step 6: Run the full worker test file to check for regressions**

Run: `uv run pytest src/tests/worker/ -v`
Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add src/app/worker/suggestion_processor.py src/tests/worker/test_suggestion_processor.py
git commit -m "fix: fail fast on non-retryable 4xx errors instead of retrying"
```

---

## Task 6: Tolerate malformed per-item LLM output (review #4)

**Files:**
- Modify: `src/app/worker/suggestion_processor.py`
- Test: `src/tests/worker/test_suggestion_processor.py` (append)

**Interfaces:**
- No new public interface — hardens the existing verse-matching loop inside `process_job`.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/worker/test_suggestion_processor.py`:
```python
from types import SimpleNamespace


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_skips_malformed_verse_id_instead_of_failing_job -v`
Expected: FAIL — the malformed `verse_id` ("not-a-valid-id") raises `ValueError` in `int(item.verse_id.split("_")[-1])`, which propagates out and marks the whole job `failed`/`queued` instead of completing with the one good item.

- [ ] **Step 3: Guard the per-item parsing**

In `src/app/worker/suggestion_processor.py`, replace:
```python
        # 3. Save each translated verse back via API
        items = []
        for item in result.translations:
            verse_num = int(item.verse_id.split("_")[-1])
            bible_text = next(
                (v for v in source_verses if v["verse_number"] == verse_num),
                None,
            )

            if bible_text:
                items.append({
                    "bibleTextId": bible_text["id"],
                    "projectUnitId": project_unit_id,
                    "suggestedText": item.target_text,
                    "modelInfo": translation_service.settings.google_ai_model,
                })
```
with:
```python
        # 3. Save each translated verse back via API. Guard each item
        # individually — one hallucinated/malformed verse_id from the LLM
        # should not fail the whole batch (see review finding #4).
        items = []
        for item in result.translations:
            try:
                verse_num = int(item.verse_id.split("_")[-1])
            except (ValueError, AttributeError):
                logger.warning(
                    f"Job {job.id}: skipping unparseable verse_id "
                    f"{item.verse_id!r} from LLM response."
                )
                continue

            bible_text = next(
                (v for v in source_verses if v["verse_number"] == verse_num),
                None,
            )

            if bible_text:
                items.append({
                    "bibleTextId": bible_text["id"],
                    "projectUnitId": project_unit_id,
                    "suggestedText": item.target_text,
                    "modelInfo": translation_service.settings.google_ai_model,
                })
            else:
                logger.warning(
                    f"Job {job.id}: LLM returned verse_id for verse "
                    f"{verse_num} which was not in the requested range; dropping."
                )

        requested_verse_numbers = {v["verse_number"] for v in source_verses}
        returned_verse_numbers = {
            int(item.verse_id.split("_")[-1])
            for item in result.translations
            if item.verse_id.rsplit("_", 1)[-1].isdigit()
        }
        missing = requested_verse_numbers - returned_verse_numbers
        if missing:
            logger.warning(
                f"Job {job.id}: LLM omitted {len(missing)} of "
                f"{len(requested_verse_numbers)} requested verses: {sorted(missing)}"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_skips_malformed_verse_id_instead_of_failing_job -v`
Expected: PASS

- [ ] **Step 5: Run the full worker test file to check for regressions**

Run: `uv run pytest src/tests/worker/ -v`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add src/app/worker/suggestion_processor.py src/tests/worker/test_suggestion_processor.py
git commit -m "fix: skip malformed LLM verse_id items instead of failing whole job"
```

---

## Task 7: Reuse one `httpx.AsyncClient` per job (review #9)

**Files:**
- Modify: `src/app/worker/suggestion_processor.py`
- Test: `src/tests/worker/test_suggestion_processor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `src/tests/worker/test_suggestion_processor.py`:
```python
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

    import httpx

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_reuses_single_httpx_client -v`
Expected: FAIL — `init_count == 2` (one client per `async with httpx.AsyncClient()` block).

- [ ] **Step 3: Open one client for the whole job**

In `src/app/worker/suggestion_processor.py`, replace the two separate `async with httpx.AsyncClient() as client:` blocks with one client wrapping both calls. Change:
```python
        # 1. Fetch context and source verses from API
        async with httpx.AsyncClient() as client:
            context_resp = await client.post(
                f"{api_base_url}/ai-suggestions/internal/context",
                headers=headers,
                json={
                    "projectUnitId": project_unit_id,
                    "bibleId": bible_id,
                    "bookCode": book_code,
                    "chapterNumber": chapter_number,
                    "verseStart": verse_start,
                    "verseEnd": verse_end,
                },
                timeout=30.0,
            )
            try:
                context_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NonRetryableJobError(
                        f"fluent-api rejected context request with "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
                raise
            context_data = context_resp.json()
```
to:
```python
        async with httpx.AsyncClient() as client:
            # 1. Fetch context and source verses from API
            context_resp = await client.post(
                f"{api_base_url}/ai-suggestions/internal/context",
                headers=headers,
                json={
                    "projectUnitId": project_unit_id,
                    "bibleId": bible_id,
                    "bookCode": book_code,
                    "chapterNumber": chapter_number,
                    "verseStart": verse_start,
                    "verseEnd": verse_end,
                },
                timeout=30.0,
            )
            try:
                context_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NonRetryableJobError(
                        f"fluent-api rejected context request with "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
                raise
            context_data = context_resp.json()
```
i.e. move the `async with httpx.AsyncClient() as client:` line up one level and dedent everything through the results push into it, removing the second, nested `async with httpx.AsyncClient() as client:` entirely. Concretely, the second block:
```python
        if items:
            async with httpx.AsyncClient() as client:
                save_resp = await client.post(
                    f"{api_base_url}/ai-suggestions/internal/results",
                    headers=headers,
                    json={"items": items},
                    timeout=30.0,
                )
                try:
                    save_resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if 400 <= exc.response.status_code < 500:
                        raise NonRetryableJobError(
                            f"fluent-api rejected results push with "
                            f"{exc.response.status_code}: {exc}"
                        ) from exc
                    raise
```
becomes (still inside the single `client` context opened above, dedented by one level, `async with` removed):
```python
        if items:
            save_resp = await client.post(
                f"{api_base_url}/ai-suggestions/internal/results",
                headers=headers,
                json={"items": items},
                timeout=30.0,
            )
            try:
                save_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NonRetryableJobError(
                        f"fluent-api rejected results push with "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
                raise
```
Everything between the two HTTP calls (target-language extraction, building `TranslateRequest`, calling `translation_service.translate_verses`, building `items`) stays at the same indentation level, now nested one level deeper inside the single `async with httpx.AsyncClient() as client:` block that spans the whole try body from the context fetch through the results push.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_reuses_single_httpx_client -v`
Expected: PASS

- [ ] **Step 5: Run the full worker test file to check for regressions**

Run: `uv run pytest src/tests/worker/ -v`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add src/app/worker/suggestion_processor.py src/tests/worker/test_suggestion_processor.py
git commit -m "refactor: reuse one httpx.AsyncClient per job instead of two"
```

---

## Task 8: Report actual inserted row count from `enqueue_suggestion_jobs` (review #7)

**Files:**
- Modify: `src/app/services/suggestions.py`
- Test: `src/tests/test_suggestions_service.py` (new)

**Interfaces:**
- Produces: `enqueue_suggestion_jobs` return message now reflects rows actually inserted, e.g. `"Queued 1 of 2 jobs (1 duplicate skipped)"` when some are deduped, or `"Queued 2 jobs"` when none are.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_suggestions_service.py`:
```python
"""
tests/test_suggestions_service.py — Tests for enqueue_suggestion_jobs'
dedup-aware response reporting.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import OwnedBase
from app.schemas.suggestions import SuggestionTriggerRequest
from app.services.suggestions import enqueue_suggestion_jobs


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})
    async with engine.begin() as conn:
        await conn.run_sync(OwnedBase.metadata.create_all)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/test_suggestions_service.py -v`
Expected: FAIL on `test_enqueue_reports_duplicates_skipped` — current code always reports `"Queued 2 jobs"` regardless of the duplicate.

- [ ] **Step 3: Use `.returning()` and report the real count**

In `src/app/services/suggestions.py`, replace:
```python
    stmt = insert(Job).values(jobs_data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])

    await db.execute(stmt)
    await db.commit()

    logger.info(f"Queued {len(jobs_data)} AI suggestion jobs")
    return SuggestionTriggerResponse(message=f"Queued {len(jobs_data)} jobs")
```
with:
```python
    stmt = insert(Job).values(jobs_data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])
    stmt = stmt.returning(Job.id)

    result = await db.execute(stmt)
    inserted_count = len(result.scalars().all())
    await db.commit()

    requested_count = len(jobs_data)
    skipped_count = requested_count - inserted_count

    if skipped_count:
        message = (
            f"Queued {inserted_count} of {requested_count} jobs "
            f"({skipped_count} duplicate skipped)"
            if skipped_count == 1
            else (
                f"Queued {inserted_count} of {requested_count} jobs "
                f"({skipped_count} duplicates skipped)"
            )
        )
    else:
        message = f"Queued {inserted_count} jobs"

    logger.info(message)
    return SuggestionTriggerResponse(message=message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/test_suggestions_service.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/app/services/suggestions.py src/tests/test_suggestions_service.py
git commit -m "fix: report actual inserted job count, accounting for dedup skips"
```

---

## Task 9: Use the shared Gemini client singleton in `translations.py` (review #6)

**Files:**
- Modify: `src/app/api/v1/endpoints/translations.py`
- Test: manual verification (no new automated test — this is a dependency-wiring change; existing translation tests, if any, must keep passing)

- [ ] **Step 1: Update imports**

Current top of `src/app/api/v1/endpoints/translations.py`:
```python
from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.dependencies import require_api_key
from app.logging.utils import get_logger
from app.schemas.translations import TranslateRequest, TranslationResult
from app.services.translation_service import TranslationService
```
Replace with (drop the now-unused `GoogleGeminiClient` import, add `GoogleGeminiDep`):
```python
from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.dependencies import GoogleGeminiDep, require_api_key
from app.logging.utils import get_logger
from app.schemas.translations import TranslateRequest, TranslationResult
from app.services.translation_service import TranslationService
```

- [ ] **Step 2: Switch the dependency function to the cached singleton**

Replace:
```python
def get_translation_service(
    settings: Settings = Depends(get_settings),
) -> TranslationService:
    gemini_client = GoogleGeminiClient(settings)
    return TranslationService(settings, gemini_client)
```
with:
```python
def get_translation_service(
    gemini_client: GoogleGeminiDep,
    settings: Settings = Depends(get_settings),
) -> TranslationService:
    return TranslationService(settings, gemini_client)
```
`GoogleGeminiDep` (`app/dependencies.py:47`) is `Annotated[GoogleGeminiClient, Depends(get_google_gemini_client)]` — its default comes from the `Annotated` metadata, not a `= Depends(...)` expression, so it must be listed before `settings` (which has an explicit default) to satisfy Python's no-default-after-default parameter ordering.

- [ ] **Step 3: Manually verify the endpoint still boots and works**

Run: `uv run pytest src/tests -v` (full suite, to catch any import-order or DI regression)
Expected: all passing

Start the app and hit the translations endpoint once to confirm the DI change resolves correctly:
Run: `uv run fastapi dev src/app/main.py &` then `curl -s -X POST localhost:8200/translations -H 'Content-Type: application/json' -d '{"target_language_name": "Spanish", "verses_to_translate": [{"verse_id": "MAT_1_1", "source_text": "test"}]}'` (expect a 200 or a clean 502 ExternalServiceException if no real API key is configured locally — either way, no DI/import error). Stop the dev server afterward.

- [ ] **Step 4: Commit**

```bash
git add src/app/api/v1/endpoints/translations.py
git commit -m "fix: reuse cached GoogleGeminiClient singleton in translations endpoint"
```

---

## Task 10: snake_case `SuggestionTriggerRequest` with camelCase wire format (review #10)

**Files:**
- Modify: `src/app/schemas/suggestions.py`
- Modify: `src/app/services/suggestions.py`
- Test: `src/tests/test_suggestions_service.py` (append)

**Interfaces:**
- Produces: `SuggestionTriggerRequest` now has snake_case Python attributes (`project_unit_id`, `bible_id`, `book_code`, `chapter_number`, `verse_start`, `verse_end`) while still accepting/emitting camelCase JSON. `req.model_dump()` calls must pass `by_alias=True` to preserve the camelCase payload stored in `Job.payload` (the worker reads it back with `.get("projectUnitId")`, unchanged).

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_suggestions_service.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/test_suggestions_service.py::test_suggestion_trigger_request_accepts_camelcase_and_exposes_snake_case -v`
Expected: FAIL — `AttributeError: 'SuggestionTriggerRequest' object has no attribute 'project_unit_id'`

- [ ] **Step 3: Add aliases to the schema**

Replace the full content of `src/app/schemas/suggestions.py`:
```python
from pydantic import BaseModel, ConfigDict, Field


class SuggestionTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_unit_id: int = Field(alias="projectUnitId")
    bible_id: int = Field(alias="bibleId")
    book_code: str = Field(alias="bookCode")
    chapter_number: int = Field(alias="chapterNumber")
    verse_start: int = Field(alias="verseStart")
    verse_end: int = Field(alias="verseEnd")


class SuggestionTriggerResponse(BaseModel):
    message: str
```

- [ ] **Step 4: Update `services/suggestions.py` to use snake_case attributes and preserve the camelCase payload**

In `src/app/services/suggestions.py`, replace:
```python
    jobs_data = [
        {
            "task_type": "ai_suggestion",
            "payload": req.model_dump(),
            "dedup_key": (
                f"ai_suggestion:{req.projectUnitId}:{req.bibleId}:{req.bookCode}:"
                f"{req.chapterNumber}:{req.verseStart}:{req.verseEnd}"
            ),
            "status": "queued",
            "retry_count": 0,
        }
        for req in requests
    ]
```
with:
```python
    jobs_data = [
        {
            "task_type": "ai_suggestion",
            "payload": req.model_dump(by_alias=True),
            "dedup_key": (
                f"ai_suggestion:{req.project_unit_id}:{req.bible_id}:{req.book_code}:"
                f"{req.chapter_number}:{req.verse_start}:{req.verse_end}"
            ),
            "status": "queued",
            "retry_count": 0,
        }
        for req in requests
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest src/tests/test_suggestions_service.py -v`
Expected: `3 passed`

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `uv run pytest src/tests -v`
Expected: all passing — the `POST /suggestions` endpoint (`app/api/v1/endpoints/suggestions.py`) still parses `list[SuggestionTriggerRequest]` from camelCase JSON bodies unchanged, since `populate_by_name=True` plus `alias=` keeps camelCase input working; FastAPI's request-body validation goes through the alias by default.

- [ ] **Step 7: Commit**

```bash
git add src/app/schemas/suggestions.py src/app/services/suggestions.py src/tests/test_suggestions_service.py
git commit -m "refactor: snake_case SuggestionTriggerRequest attributes, keep camelCase wire format"
```

---

## Task 11: Remove dead context-retrieval constants (review #11)

**Files:**
- Modify: `src/app/core/constants.py`

- [ ] **Step 1: Confirm they're unused**

Run: `grep -rn "MAX_CONTEXT_VERSES_TOTAL\|MAX_CONTEXT_VERSES_FTS" src/`
Expected: only the definitions in `src/app/core/constants.py`, no other references.

- [ ] **Step 2: Remove the dead constants and their section**

In `src/app/core/constants.py`, delete:
```python

# ---------------------------------------------------------------------------
# Context Retrieval (Translation Memory)
# ---------------------------------------------------------------------------

# Total number of context verse pairs (source + target) to include
# in the Translation Memory prompt sent to the LLM.
MAX_CONTEXT_VERSES_TOTAL = 10

# Of the total, how many slots are reserved for FTS (lexical similarity)
# matches. The remainder is filled by proximity/genre-based matches.
MAX_CONTEXT_VERSES_FTS = 5
```
Also update the module docstring at the top of the file to remove the now-inaccurate "context retrieval" mention:
```python
"""
constants.py — Centralized configuration constants for the AI suggestion system.

All tunable values for the suggestion queue and background worker are
defined here. Import from this module instead of hardcoding values in
business logic. Context retrieval (translation memory selection) happens
server-side in fluent-api, not in this service.
"""
```

- [ ] **Step 3: Run the full suite to confirm nothing broke**

Run: `uv run pytest src/tests -v`
Expected: all passing

- [ ] **Step 4: Commit**

```bash
git add src/app/core/constants.py
git commit -m "chore: remove unused context-retrieval constants (implemented in fluent-api, not here)"
```

---

## Task 12: Structured Gemini output via `response_schema` (review #12)

**Files:**
- Modify: `src/app/core/ai_clients/google_gemini.py`
- Modify: `src/app/services/translation_service.py`
- Test: `src/tests/test_google_gemini.py` (append — follow the existing patching pattern in that file)

**Interfaces:**
- Produces: `GoogleGeminiClient.generate_content(..., response_schema: type | None = None)` — threads a Pydantic model class through to `types.GenerateContentConfig(response_schema=...)`.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_google_gemini.py` (matching the file's existing `@patch("app.core.ai_clients.google_gemini.genai")` style — read the file's existing tests first to match exact mock setup for `_client.aio.models.generate_content`):
```python
@patch("app.core.ai_clients.google_gemini.genai")
@pytest.mark.asyncio
async def test_generate_content_passes_response_schema_through(mock_genai: MagicMock) -> None:
    from pydantic import BaseModel

    class _Schema(BaseModel):
        translations: list[dict]

    mock_response = MagicMock()
    mock_response.text = "{}"
    mock_client_instance = MagicMock()
    mock_client_instance.aio.models.generate_content = AsyncMock(return_value=mock_response)
    mock_genai.Client.return_value = mock_client_instance

    settings = _settings_with_key()
    client = GoogleGeminiClient(settings=settings)

    await client.generate_content(
        prompt="translate this",
        response_mime_type="application/json",
        response_schema=_Schema,
    )

    _, kwargs = mock_client_instance.aio.models.generate_content.call_args
    assert kwargs["config"].response_schema is _Schema
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/test_google_gemini.py::test_generate_content_passes_response_schema_through -v`
Expected: FAIL — `TypeError: generate_content() got an unexpected keyword argument 'response_schema'`

- [ ] **Step 3: Thread `response_schema` through the client**

In `src/app/core/ai_clients/google_gemini.py`, replace:
```python
    async def generate_content(
        self,
        prompt: str,
        system_instruction: str | None = None,
        response_mime_type: str | None = None,
    ) -> str:
        """Send a prompt to Gemini and return the text response.

        Raises:
            ExternalServiceException: If the SDK raises any error.
        """
        try:
            config = None
            if system_instruction or response_mime_type:
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type=response_mime_type,
                )
```
with:
```python
    async def generate_content(
        self,
        prompt: str,
        system_instruction: str | None = None,
        response_mime_type: str | None = None,
        response_schema: type | None = None,
    ) -> str:
        """Send a prompt to Gemini and return the text response.

        Args:
            response_schema: Optional Pydantic model class describing the
                expected JSON shape. When set alongside
                response_mime_type="application/json", the SDK validates
                and structures the model's output server-side, removing
                the need for manual fence-stripping/json.loads downstream.

        Raises:
            ExternalServiceException: If the SDK raises any error.
        """
        try:
            config = None
            if system_instruction or response_mime_type or response_schema:
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type=response_mime_type,
                    response_schema=response_schema,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/test_google_gemini.py::test_generate_content_passes_response_schema_through -v`
Expected: PASS

- [ ] **Step 5: Use it from `TranslationService` and drop the manual fence-stripping**

In `src/app/services/translation_service.py`, replace:
```python
        try:
            response_text = await self.gemini_client.generate_content(
                prompt=full_prompt,
                system_instruction=system_instruction,
                response_mime_type="application/json",
            )
            
            # Clean up potential markdown formatting if the model still outputs it despite response_mime_type
            clean_text = response_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
                
            parsed_json = json.loads(clean_text)
            return TranslationResult.model_validate(parsed_json)
```
with:
```python
        try:
            response_text = await self.gemini_client.generate_content(
                prompt=full_prompt,
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=TranslationResult,
            )
            parsed_json = json.loads(response_text)
            return TranslationResult.model_validate(parsed_json)
```

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `uv run pytest src/tests -v`
Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add src/app/core/ai_clients/google_gemini.py src/app/services/translation_service.py src/tests/test_google_gemini.py
git commit -m "feat: use Gemini structured output (response_schema) instead of manual JSON fence-stripping"
```

---

## Task 13: Reject insecure default secrets in production (review #13)

**Files:**
- Modify: `src/app/config.py`
- Test: `src/tests/test_config.py` (new)

**Interfaces:**
- Produces: `Settings()` raises `ValueError` at startup when `environment == "production"` and `secret_key` or `api_service_key` still equal their insecure placeholder defaults.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_config.py`:
```python
"""
tests/test_config.py — Tests for the production-safety config validator.
"""

import pytest

from app.config import Settings


def _base_kwargs(**overrides):
    kwargs = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/test",
        "environment": "production",
        "secret_key": "a-real-production-secret",
        "api_service_key": "a-real-production-service-key",
    }
    kwargs.update(overrides)
    return kwargs


def test_production_settings_accepts_real_secrets():
    settings = Settings(**_base_kwargs())
    assert settings.environment == "production"


def test_production_settings_rejects_default_secret_key():
    with pytest.raises(ValueError, match="secret_key"):
        Settings(**_base_kwargs(secret_key="your-secret-key-change-in-production"))


def test_production_settings_rejects_default_api_service_key():
    with pytest.raises(ValueError, match="api_service_key"):
        Settings(**_base_kwargs(api_service_key="dev-inbound-key-replace-me"))


def test_development_settings_allows_default_secrets():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
        environment="development",
    )
    assert settings.secret_key == "your-secret-key-change-in-production"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/test_config.py -v`
Expected: FAIL on the two `rejects_default_*` tests — `Settings(...)` currently constructs successfully with the placeholder values even in production.

- [ ] **Step 3: Extend the validator**

In `src/app/config.py`, replace:
```python
    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Force show_stack_traces off in production, regardless of env var."""
        if self.environment == "production" and self.show_stack_traces:
            self.show_stack_traces = False
        return self
```
with:
```python
    _INSECURE_SECRET_KEY_DEFAULT = "your-secret-key-change-in-production"
    _INSECURE_API_SERVICE_KEY_DEFAULT = "dev-inbound-key-replace-me"

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Force show_stack_traces off in production, and refuse to boot
        with known placeholder secrets in production."""
        if self.environment == "production" and self.show_stack_traces:
            self.show_stack_traces = False

        if self.environment == "production":
            if self.secret_key == self._INSECURE_SECRET_KEY_DEFAULT:
                raise ValueError(
                    "secret_key is still set to its insecure development "
                    "default — set a real SECRET_KEY in production."
                )
            if self.api_service_key == self._INSECURE_API_SERVICE_KEY_DEFAULT:
                raise ValueError(
                    "api_service_key is still set to its insecure development "
                    "default — set a real API_SERVICE_KEY in production."
                )

        return self
```

Note: `_INSECURE_SECRET_KEY_DEFAULT` / `_INSECURE_API_SERVICE_KEY_DEFAULT` as plain class attributes (not `Field(...)`) are not treated as pydantic model fields since they're leading-underscore names — `pydantic-settings` ignores private/underscore-prefixed class attributes for field generation, so this doesn't add new settings fields or env vars.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/test_config.py -v`
Expected: `4 passed`

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest src/tests -v`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add src/app/config.py src/tests/test_config.py
git commit -m "fix: refuse to boot in production with default placeholder secrets"
```

---

## Final verification

- [ ] Run the full suite one more time: `uv run pytest src/tests -v` — expect all green.
- [ ] Run lint: `uv run ruff check src` — fix any new warnings introduced by these changes.
- [ ] Run type-check: `uv run mypy src` — fix any new errors (pay particular attention to Task 9's `GoogleGeminiDep` parameter reordering and Task 12's `type | None` annotation).
- [ ] Re-read `AI_SUGGESTIONS_REVIEW.md` top-to-bottom and confirm every High/Medium item (#1–#7, #9, #10, #11, #12, #13) maps to a completed task above, and that #8 and #14 are intentionally left as out-of-scope per the Global Constraints section.
