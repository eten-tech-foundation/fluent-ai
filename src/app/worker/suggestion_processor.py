"""
suggestion_processor.py — Background worker for AI translation suggestions.

This module runs as an asyncio task started in main.py's lifespan.
It continuously polls the ai.jobs table for 'queued' jobs, processes
them one at a time, and pushes results back to fluent-api over HTTP.

Job Processing Pipeline:
    1. Claim a queued job using SELECT FOR UPDATE SKIP LOCKED
       (prevents race conditions if multiple workers are running).
    2. Fetch source verses and translation context from fluent-api
       via POST /internal/suggestion-context.
    3. Call the TranslationService (Google Gemini) to generate translations.
    4. Push translated verses back to fluent-api via
       POST /internal/ai-suggestions.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.logging.utils import get_logger
from app.models.job import Job
import httpx
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.services.translation_service import TranslationService
from app.schemas.translations import TranslateRequest, VerseToTranslate
from app.config import get_settings
from app.core.constants import (
    WORKER_POLL_INTERVAL_SECONDS,
    WORKER_MAX_CONSECUTIVE_FAILURES,
    MAX_JOB_RETRIES,
)

logger = get_logger(__name__)


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
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # 1. Fetch context and source verses from API
        async with httpx.AsyncClient() as client:
            context_resp = await client.post(
                f"{api_base_url}/internal/suggestion-context",
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
            context_resp.raise_for_status()
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

        if items:
            async with httpx.AsyncClient() as client:
                save_resp = await client.post(
                    f"{api_base_url}/internal/ai-suggestions",
                    headers=headers,
                    json={"items": items},
                    timeout=30.0,
                )
                save_resp.raise_for_status()

        job.status = "completed"
        await db.commit()
        logger.info(f"Job {job.id} completed successfully.")

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
            logger.error(
                f"Worker loop error (failure #{consecutive_failures}): {e}"
            )

            # M3 Fix: Exponential backoff on repeated failures
            if consecutive_failures >= WORKER_MAX_CONSECUTIVE_FAILURES:
                backoff = min(
                    WORKER_POLL_INTERVAL_SECONDS * (2 ** (consecutive_failures - WORKER_MAX_CONSECUTIVE_FAILURES)),
                    300,  # Cap at 5 minutes
                )
                logger.warning(
                    f"Worker backing off for {backoff}s after "
                    f"{consecutive_failures} consecutive failures."
                )
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)
