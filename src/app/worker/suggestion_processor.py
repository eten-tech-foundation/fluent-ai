"""
suggestion_processor.py — Background worker for AI translation suggestions.

This module runs as an asyncio task started in main.py's lifespan.
It continuously polls the ai.jobs table for 'queued' jobs, processes
them one at a time, and pushes results back to fluent-api over HTTP.

Job Processing Pipeline:
    1. Claim a queued job using SELECT FOR UPDATE SKIP LOCKED
       (prevents race conditions if multiple workers are running).
    2. Fetch source verses and translation context from fluent-api
       via POST /ai-suggestions/internal/context.
    3. Call the TranslationService (Google Gemini) to generate translations.
    4. Push translated verses back to fluent-api via
       POST /ai-suggestions/internal/results.
    5. Mark the job as completed.

Retry Logic:
    On failure, the job's retry_count is incremented. If it hasn't
    exceeded MAX_JOB_RETRIES, the job is re-queued. Otherwise it is
    permanently marked as 'failed' with the error message saved.

Error Resilience:
    The outer worker loop uses exponential backoff when encountering
    repeated failures (e.g., database connection lost). This prevents
    the worker from spinning hot and filling logs.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.database import AsyncSessionLocal
from app.logging.utils import get_logger
from app.models.job import Job

from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.services.translation_service import TranslationService
from app.schemas.translations import TranslateRequest, VerseToTranslate
from app.config import get_settings
from app.core.constants import (
    WORKER_POLL_INTERVAL_SECONDS,
    WORKER_MAX_CONSECUTIVE_FAILURES,
    MAX_JOB_RETRIES,
    STALE_PROCESSING_TIMEOUT_MINUTES,
)

logger = get_logger(__name__)


class NonRetryableJobError(Exception):
    """Raised for failures that retrying cannot fix (e.g. a 4xx from
    fluent-api, or a permanently malformed request payload). Jobs that
    raise this go straight to 'failed' without consuming retry attempts."""


async def process_job(
    db: AsyncSession,
    job: Job,
    translation_service: TranslationService,
):
    """
    Process a single AI suggestion job.
    """
    try:
        # Mark as processing
        job.status = "processing"
        job.error_message = None
        await db.commit()

        payload = job.payload
        project_unit_id = payload.get("projectUnitId")
        bible_id = payload.get("bibleId")
        book_code = payload.get("bookCode")
        chapter_number = payload.get("chapterNumber")
        verse_start = payload.get("verseStart")
        verse_end = payload.get("verseEnd")

        settings = translation_service.settings
        api_base_url = settings.api_base_url.rstrip("/")
        api_key = settings.api_service_key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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

            target_language_name = context_data.get("targetLanguageName", "Unknown")
            context_verses = context_data.get("contextVerses", [])
            source_verses = context_data.get("sourceVerses", [])

            if not source_verses:
                job.status = "failed"
                job.error_message = (
                    f"No source verses found for {book_code} "
                    f"{chapter_number}:{verse_start}-{verse_end}"
                )
                await db.commit()
                return

            # 2. Build the translation request and call the LLM
            request = TranslateRequest(
                target_language_name=target_language_name,
                context_verses=context_verses,
                verses_to_translate=[
                    VerseToTranslate(
                        verse_id=f"{book_code}_{chapter_number}_{v['verse_number']}",
                        source_text=v["text"],
                    )
                    for v in source_verses
                ],
            )

            result = await translation_service.translate_verses(request)

            # 3. Save each translated verse back via API. Guard each item
            # individually — one hallucinated/malformed verse_id from the LLM
            # should not fail the whole batch (see review finding #4).
            items = []
            parsed_verse_numbers = set()
            for item in result.translations:
                try:
                    verse_num = int(item.verse_id.split("_")[-1])
                except ValueError, AttributeError:
                    logger.warning(
                        f"Job {job.id}: skipping unparseable verse_id "
                        f"{item.verse_id!r} from LLM response."
                    )
                    continue

                parsed_verse_numbers.add(verse_num)

                bible_text = next(
                    (v for v in source_verses if v["verse_number"] == verse_num),
                    None,
                )

                if bible_text:
                    items.append(
                        {
                            "bibleTextId": bible_text["id"],
                            "projectUnitId": project_unit_id,
                            "suggestedText": item.target_text,
                            "modelInfo": translation_service.settings.google_ai_model,
                        }
                    )
                else:
                    logger.warning(
                        f"Job {job.id}: LLM returned verse_id for verse "
                        f"{verse_num} which was not in the requested range; dropping."
                    )

            requested_verse_numbers = {v["verse_number"] for v in source_verses}
            missing = requested_verse_numbers - parsed_verse_numbers
            if missing:
                logger.warning(
                    f"Job {job.id}: LLM omitted {len(missing)} of "
                    f"{len(requested_verse_numbers)} requested verses: {sorted(missing)}"
                )

            if not items:
                job.status = "failed"
                job.error_message = (
                    f"No valid translations to save for {book_code} "
                    f"{chapter_number}:{verse_start}-{verse_end} — all "
                    f"{len(result.translations)} LLM-returned item(s) were "
                    f"malformed or out of the requested range."
                )
                await db.commit()
                return

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

        job.status = "completed"
        await db.commit()
        logger.info(f"Job {job.id} completed successfully.")

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

        # Retry logic: re-queue if under the retry limit — unless this is a
        # permanent failure that retrying cannot fix.
        if (
            not isinstance(e, NonRetryableJobError)
            and current_retry_count < MAX_JOB_RETRIES
        ):
            new_retry_count = current_retry_count + 1
            job.retry_count = new_retry_count
            job.status = "queued"
            job.error_message = (
                f"Retry {new_retry_count}/{MAX_JOB_RETRIES}: {str(e)[:500]}"
            )
            logger.info(
                f"Re-queuing job {job_id} (retry {new_retry_count}/{MAX_JOB_RETRIES})"
            )
        else:
            job.status = "failed"
            job.error_message = (
                f"Permanently failed after {MAX_JOB_RETRIES} retries: {str(e)[:500]}"
            )
            logger.error(
                f"Job {job_id} permanently failed after {MAX_JOB_RETRIES} retries."
            )

        await db.commit()


async def reclaim_stale_jobs(db: AsyncSession) -> int:
    """Requeue jobs stuck in 'processing' longer than the stale timeout.

    Handles the case where a worker crashed or was killed mid-job: the row's
    FOR UPDATE lock is released the moment status flips to 'processing'
    (see process_job), so a crash after that point leaves the row orphaned
    with no lock and no worker watching it. This sweep runs once per poll
    cycle and requeues anything whose updated_at is older than the timeout.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        minutes=STALE_PROCESSING_TIMEOUT_MINUTES
    )
    stmt = (
        update(Job)
        .where(Job.status == "processing", Job.updated_at < cutoff)
        .values(status="queued")
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount:  # type: ignore[attr-defined]
        logger.warning(f"Reclaimed {result.rowcount} stale 'processing' job(s).")  # type: ignore[attr-defined]
    return result.rowcount  # type: ignore[attr-defined]


async def worker_loop():
    """
    Main background worker loop.

    Runs indefinitely as an asyncio task. Polls ai.jobs
    for 'queued' jobs and processes them one at a time.

    Uses SELECT FOR UPDATE SKIP LOCKED to safely claim jobs,
    preventing race conditions if multiple workers are running.

    Implements exponential backoff on repeated failures to avoid
    spinning hot when the database or external services are down.
    """
    logger.info("Starting AI Suggestion Worker Loop")
    settings = get_settings()
    gemini_client = GoogleGeminiClient(settings)
    translation_service = TranslationService(settings, gemini_client)

    consecutive_failures = 0

    while True:
        try:
            async with AsyncSessionLocal() as db:
                await reclaim_stale_jobs(db)

                # ----------------------------------------------------------
                # H1 Fix: Use FOR UPDATE SKIP LOCKED to claim jobs safely.
                # This prevents two workers from picking the same job.
                # ----------------------------------------------------------
                query = (
                    select(Job)
                    .where(Job.status == "queued")
                    .order_by(Job.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                result = await db.execute(query)
                job = result.scalar_one_or_none()

                if job:
                    await process_job(db, job, translation_service)
                    consecutive_failures = 0  # Reset on success
                else:
                    # No jobs available — sleep before polling again
                    await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"Worker loop error (failure #{consecutive_failures}): {e}")

            # M3 Fix: Exponential backoff on repeated failures
            if consecutive_failures >= WORKER_MAX_CONSECUTIVE_FAILURES:
                backoff = min(
                    WORKER_POLL_INTERVAL_SECONDS
                    * (2 ** (consecutive_failures - WORKER_MAX_CONSECUTIVE_FAILURES)),
                    300,  # Cap at 5 minutes
                )
                logger.warning(
                    f"Worker backing off for {backoff}s after "
                    f"{consecutive_failures} consecutive failures."
                )
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)
