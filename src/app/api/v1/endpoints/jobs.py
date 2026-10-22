from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    JOB_STATS_DEFAULT_WINDOW_HOURS,
    JOB_STATS_MAX_WINDOW_HOURS,
    JOB_STATS_MIN_WINDOW_HOURS,
)
from app.dependencies import get_db, require_api_key
from app.schemas.jobs import JobStatsResponse
from app.services.jobs import get_job_stats

router = APIRouter()


@router.get(
    "/stats",
    response_model=JobStatsResponse,
    summary="Report ai.jobs pipeline health",
    dependencies=[Depends(require_api_key)],
)
async def job_stats(
    window_hours: int = Query(
        default=JOB_STATS_DEFAULT_WINDOW_HOURS,
        ge=JOB_STATS_MIN_WINDOW_HOURS,
        le=JOB_STATS_MAX_WINDOW_HOURS,
    ),
    db: AsyncSession = Depends(get_db),
) -> JobStatsResponse:
    """
    Report ai.jobs counts by status, read from the table on every call.
    """
    return await get_job_stats(db, window_hours)
