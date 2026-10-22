from hashlib import sha256
import json

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.utils import get_logger
from app.models.job import Job
from app.schemas.suggestions import SuggestionTriggerRequest, SuggestionTriggerResponse

logger = get_logger(__name__)


def _dedup_key(request: SuggestionTriggerRequest) -> str:
    if request.pericope_number is not None:
        # Hash the complete identity to avoid separator ambiguity and stay within
        # jobs.dedup_key's 255-character limit for arbitrary pericope numbers.
        identity = json.dumps(request.model_dump(by_alias=True), sort_keys=True)
        return f"ai_suggestion:heading:{sha256(identity.encode()).hexdigest()}"
    return (
        f"ai_suggestion:{request.project_unit_id}:{request.bible_id}:{request.book_code}:"
        f"{request.chapter_number}:{request.verse_start}:{request.verse_end}"
    )


async def enqueue_suggestion_jobs(
    db: AsyncSession,
    requests: list[SuggestionTriggerRequest],
) -> SuggestionTriggerResponse:
    """
    Enqueue AI translation suggestion jobs in the generic jobs table.
    """
    if not requests:
        return SuggestionTriggerResponse(message="No jobs provided")

    jobs_data = [
        {
            "task_type": "ai_suggestion",
            "payload": req.model_dump(by_alias=True, exclude_none=True),
            "dedup_key": _dedup_key(req),
            "status": "queued",
            "retry_count": 0,
        }
        for req in requests
    ]

    # A failed job is a retry path, not a tombstone: reset it so the
    # re-trigger runs it again. queued/processing/completed rows stay deduped.
    # The payload is left alone because an equal dedup_key implies an equal
    # request.
    requeue_stmt = (
        update(Job)
        .where(
            Job.dedup_key.in_({job["dedup_key"] for job in jobs_data}),
            Job.status == "failed",
        )
        .values(status="queued", retry_count=0, error_message=None)
        .returning(Job.id)
    )
    requeued_count = len((await db.execute(requeue_stmt)).scalars().all())

    stmt = insert(Job).values(jobs_data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])
    stmt = stmt.returning(Job.id)  # type: ignore[assignment]

    result = await db.execute(stmt)
    inserted_count = len(result.scalars().all())
    await db.commit()

    requested_count = len(jobs_data)
    skipped_count = requested_count - inserted_count - requeued_count

    notes = []
    if requeued_count:
        notes.append(
            f"{requeued_count} failed job{'' if requeued_count == 1 else 's'} requeued"
        )
    if skipped_count:
        notes.append(
            f"{skipped_count} duplicate{'' if skipped_count == 1 else 's'} skipped"
        )
    if notes:
        message = (
            f"Queued {inserted_count} of {requested_count} jobs ({', '.join(notes)})"
        )
    else:
        message = f"Queued {inserted_count} jobs"

    logger.info(message)
    return SuggestionTriggerResponse(
        message=message,
        queued=inserted_count,
        requeued=requeued_count,
        skipped=skipped_count,
    )
