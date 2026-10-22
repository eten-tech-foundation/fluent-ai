from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_api_key
from app.schemas.jobs import JobStatsResponse
from app.services.job_stats import get_job_stats

router = APIRouter()


@router.get(
    "/stats",
    response_model=JobStatsResponse,
    summary="Report ai.jobs pipeline health",
    dependencies=[Depends(require_api_key)],
)
async def job_stats(
    window_hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
) -> JobStatsResponse:
    """
    Report ai.jobs counts by status, read from the table on every call.
    """
    return await get_job_stats(db, window_hours)
