from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.database import get_db
from app.logging.utils import get_logger
from app.models.job import Job
from app.schemas.suggestions import SuggestionTriggerRequest
from app.security.auth import require_api_key

logger = get_logger(__name__)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])

@router.post(
    "",
    summary="Trigger AI suggestion jobs",
    dependencies=[Depends(require_api_key)],
)
async def trigger_suggestions(
    requests: list[SuggestionTriggerRequest],
    db: AsyncSession = Depends(get_db),
):
    """
    Enqueue AI translation suggestion jobs in the generic jobs table.
    """
    if not requests:
        return {"message": "No jobs provided"}

    jobs_data = []
    for req in requests:
        dedup_key = f"ai_suggestion:{req.projectUnitId}:{req.bibleId}:{req.bookCode}:{req.chapterNumber}:{req.verseStart}:{req.verseEnd}"
        jobs_data.append({
            "task_type": "ai_suggestion",
            "payload": req.model_dump(),
            "dedup_key": dedup_key,
            "status": "queued",
            "retry_count": 0,
        })

    stmt = insert(Job).values(jobs_data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])
    
    await db.execute(stmt)
    await db.commit()

    logger.info(f"Queued {len(jobs_data)} AI suggestion jobs")
    return {"message": f"Queued {len(jobs_data)} jobs"}
