"""
suggestion_processor.py — Background worker for AI translation suggestions.

This module runs as an asyncio task started in main.py's lifespan.
It continuously polls the ai.ai_suggestion_jobs table for 'queued'
jobs, processes them one at a time, and saves the results to
ai.ai_suggestions.

Job Processing Pipeline:
    1. Claim a queued job using SELECT FOR UPDATE SKIP LOCKED
       (prevents race conditions if multiple workers are running).
    2. Fetch the source verses from bible_texts.
    3. Retrieve context (Translation Memory) using hybrid FTS + proximity.
    4. Look up the target language name from the languages table.
    5. Call the TranslationService (Google Gemini) to generate translations.
    6. Save each translated verse as an AiSuggestion record.
    7. Mark the job as completed.

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
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.logging.utils import get_logger
from app.models.ai_suggestion import AiSuggestion, AiSuggestionJob
from app.internal.platform_models import BibleText, Book, Language, ProjectUnit
from app.internal.project import Project
from app.services.context_retrieval import get_context_verses_for_prompt
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.services.translation_service import TranslationService
from app.schemas.translations import TranslateRequest, VerseToTranslate
from app.config import get_settings
from app.core.constants import (
    WORKER_POLL_INTERVAL_SECONDS,
    WORKER_MAX_CONSECUTIVE_FAILURES,
    MAX_CONTEXT_VERSES_TOTAL,
    MAX_JOB_RETRIES,
)

logger = get_logger(__name__)


async def _resolve_target_language_name(
    db: AsyncSession, project_unit_id: int
) -> str:
    """
    Look up the human-readable name of the project's target language.

    Joins ProjectUnit → Project → Language to get lang_name.
    Returns 'Unknown' if the lookup fails (should not happen with
    valid data, but prevents a crash).
    """
    stmt = (
        select(Language.lang_name)
        .join(Project, Project.target_language == Language.id)
        .join(ProjectUnit, ProjectUnit.project_id == Project.id)
        .where(ProjectUnit.id == project_unit_id)
        .limit(1)
    )
    result = await db.execute(stmt)
    name = result.scalar_one_or_none()

    if not name:
        logger.error(
            f"Could not resolve target language name for "
            f"project_unit_id={project_unit_id}. Job will fail."
        )
        raise ValueError(f"Target language not found for project_unit_id={project_unit_id}")

    return name


async def process_job(
    db: AsyncSession,
    job: AiSuggestionJob,
    translation_service: TranslationService,
):
    """
    Process a single AI suggestion job.

    This function is called by the worker loop after claiming a job.
    On success, suggestions are saved and the job is marked 'completed'.
    On failure, the job is retried (up to MAX_JOB_RETRIES) or marked 'failed'.
    """
    try:
        # Mark as processing
        job.status = "processing"
        job.error_message = None
        await db.commit()

        # ------------------------------------------------------------------
        # Step 1: Fetch the source verses to translate
        # ------------------------------------------------------------------
        verses_query = (
            select(BibleText)
            .join(Book, BibleText.book_id == Book.id)
            .where(
                BibleText.bible_id == job.bible_id,
                Book.code == job.book_code.upper(),
                BibleText.chapter_number == job.chapter_number,
                BibleText.verse_number >= job.verse_start,
                BibleText.verse_number <= job.verse_end,
            )
        )
        verses_result = await db.execute(verses_query)
        verses_to_translate = verses_result.scalars().all()

        if not verses_to_translate:
            job.status = "failed"
            job.error_message = (
                f"No source verses found for {job.book_code} "
                f"{job.chapter_number}:{job.verse_start}-{job.verse_end}"
            )
            await db.commit()
            return

        # ------------------------------------------------------------------
        # Step 2: Retrieve context (Translation Memory) for the prompt
        # ------------------------------------------------------------------
        context_verses = await get_context_verses_for_prompt(
            db,
            job.project_unit_id,
            job.bible_id,
            job.book_code,
            job.chapter_number,
            job.verse_start,
            limit=MAX_CONTEXT_VERSES_TOTAL,
        )

        # ------------------------------------------------------------------
        # Step 3: Resolve the target language name for the LLM prompt
        # ------------------------------------------------------------------
        target_language_name = await _resolve_target_language_name(
            db, job.project_unit_id
        )

        # ------------------------------------------------------------------
        # Step 4: Build the translation request and call the LLM
        # ------------------------------------------------------------------
        request = TranslateRequest(
            target_language_name=target_language_name,
            context_verses=[cv.to_dict() for cv in context_verses],
            verses_to_translate=[
                VerseToTranslate(
                    verse_id=f"{job.book_code}_{job.chapter_number}_{v.verse_number}",
                    source_text=v.text,
                )
                for v in verses_to_translate
            ],
        )

        result = await translation_service.translate_verses(request)

        # ------------------------------------------------------------------
        # Step 5: Save each translated verse as an AiSuggestion
        # ------------------------------------------------------------------
        for item in result.translations:
            # Parse verse number from the verse_id returned by the LLM
            verse_num = int(item.verse_id.split("_")[-1])
            bible_text = next(
                (v for v in verses_to_translate if v.verse_number == verse_num),
                None,
            )

            if bible_text:
                stmt = (
                    insert(AiSuggestion)
                    .values(
                        bible_text_id=bible_text.id,
                        project_unit_id=job.project_unit_id,
                        suggested_text=item.target_text,
                        model_info=translation_service.settings.google_ai_model,
                    )
                    .on_conflict_do_update(
                        index_elements=["bible_text_id", "project_unit_id"],
                        set_={
                            "suggested_text": item.target_text,
                            "model_info": translation_service.settings.google_ai_model,
                        },
                    )
                )
                await db.execute(stmt)

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

    Runs indefinitely as an asyncio task. Polls ai.ai_suggestion_jobs
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
                    select(AiSuggestionJob)
                    .where(AiSuggestionJob.status == "queued")
                    .order_by(AiSuggestionJob.created_at.asc())
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
