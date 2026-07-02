from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.utils import get_logger
from app.models.job import Job
from app.schemas.suggestions import SuggestionTriggerRequest, SuggestionTriggerResponse

logger = get_logger(__name__)


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

    stmt = insert(Job).values(jobs_data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])

    await db.execute(stmt)
    await db.commit()

    logger.info(f"Queued {len(jobs_data)} AI suggestion jobs")
    return SuggestionTriggerResponse(message=f"Queued {len(jobs_data)} jobs")
