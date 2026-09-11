from hashlib import sha256
import json

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

    stmt = insert(Job).values(jobs_data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])
    stmt = stmt.returning(Job.id)  # type: ignore[assignment]

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
