"""
suggestion_queue.py — Enqueuing logic for AI translation suggestion jobs.

This service is called by the /init and /queue-next API endpoints.
It determines which verses still need suggestions, validates that
those verses actually exist in the bible, groups contiguous missing
verses into batched jobs, and inserts them into ai.ai_suggestion_jobs.

Deduplication:
    Before creating a job, this service checks for existing jobs
    (of any status) that already cover the requested verses.
    This prevents duplicate work when the client calls /queue-next
    multiple times for the same verse range.

Transaction Ownership:
    This service does NOT commit. The calling layer (FastAPI's get_db
    dependency) owns the transaction and commits on success.
"""

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.internal.models import AiSuggestionJob, BibleText, Book
from app.logging.utils import get_logger
from app.core.constants import SUGGESTION_QUEUE_N_AHEAD

logger = get_logger(__name__)


async def queue_suggestions_ahead(
    db: AsyncSession,
    project_unit_id: int,
    bible_id: int,
    book_code: str,
    chapter_number: int,
    verse_start: int,
    n_ahead: int = SUGGESTION_QUEUE_N_AHEAD
) -> None:
    """
    Queue AI suggestion jobs for the next N verses, skipping any
    that already have a job (queued, processing, or completed).

    Steps:
    1. Find the actual max verse number in the chapter to avoid
       queuing non-existent verses.
    2. Batch-check which verses in the range already have jobs.
    3. Group the remaining missing verses into contiguous blocks.
    4. Insert one AiSuggestionJob per block.
    """
    verse_end = verse_start + n_ahead - 1

    # ------------------------------------------------------------------
    # H3 Fix: Validate that the requested verses actually exist.
    # Clamp verse_end to the actual max verse in the chapter.
    # ------------------------------------------------------------------
    max_verse_stmt = (
        select(func.max(BibleText.verse_number))
        .join(Book, BibleText.book_id == Book.id)
        .where(
            BibleText.bible_id == bible_id,
            Book.code == book_code,
            BibleText.chapter_number == chapter_number
        )
    )
    max_verse_result = await db.execute(max_verse_stmt)
    max_verse = max_verse_result.scalar_one_or_none()

    if max_verse is None:
        logger.warning(
            f"No verses found for {book_code} chapter {chapter_number} "
            f"in bible {bible_id}. Nothing to queue."
        )
        return

    # Clamp the range to actual verse count
    verse_end = min(verse_end, max_verse)
    if verse_start > max_verse:
        logger.info(
            f"verse_start ({verse_start}) exceeds max verse ({max_verse}) "
            f"for {book_code} chapter {chapter_number}. Nothing to queue."
        )
        return

    # ------------------------------------------------------------------
    # H2 Fix: Single batch query instead of N+1 loop.
    # Fetch all verses in [verse_start, verse_end] that already have jobs.
    # ------------------------------------------------------------------
    # We need to find which individual verse numbers are covered by
    # existing jobs. A job covers verse v if verse_start <= v <= verse_end.
    # We use generate_series to expand job ranges into individual verses.
    existing_verses_query = (
        select(AiSuggestionJob.verse_start, AiSuggestionJob.verse_end)
        .where(
            AiSuggestionJob.project_unit_id == project_unit_id,
            AiSuggestionJob.bible_id == bible_id,
            AiSuggestionJob.book_code == book_code,
            AiSuggestionJob.chapter_number == chapter_number,
            # Job overlaps with our requested range
            AiSuggestionJob.verse_start <= verse_end,
            AiSuggestionJob.verse_end >= verse_start,
        )
    )
    result = await db.execute(existing_verses_query)
    existing_jobs = result.all()

    # Expand job ranges into a set of covered verse numbers
    covered_verses = set()
    for job_start, job_end in existing_jobs:
        for v in range(max(job_start, verse_start), min(job_end, verse_end) + 1):
            covered_verses.add(v)

    # Compute missing verses
    missing_verses = sorted(
        v for v in range(verse_start, verse_end + 1) if v not in covered_verses
    )

    if not missing_verses:
        logger.info(
            f"All verses {verse_start}-{verse_end} are already queued or completed."
        )
        return

    # ------------------------------------------------------------------
    # Group contiguous missing verses into job blocks.
    # e.g., [1, 2, 3, 6, 7] → [(1, 3), (6, 7)]
    # ------------------------------------------------------------------
    blocks = []
    start = missing_verses[0]
    prev = missing_verses[0]

    for v in missing_verses[1:]:
        if v == prev + 1:
            prev = v
        else:
            blocks.append((start, prev))
            start = v
            prev = v
    blocks.append((start, prev))

    for b_start, b_end in blocks:
        logger.info(
            f"Queuing suggestion job for {book_code} chapter {chapter_number}, "
            f"verses {b_start}-{b_end}"
        )
        new_job = AiSuggestionJob(
            project_unit_id=project_unit_id,
            bible_id=bible_id,
            book_code=book_code,
            chapter_number=chapter_number,
            verse_start=b_start,
            verse_end=b_end,
            status='queued'
        )
        db.add(new_job)

    # H4 Fix: Do NOT commit here. The get_db() dependency owns the
    # transaction and will commit when the request handler returns.
