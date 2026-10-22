from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.filters import scrub_text
from app.models.job import Job
from app.schemas.jobs import JobStatsResponse, JobStatusCounts, LatestJobFailure


def _as_utc(value: datetime | None) -> datetime | None:
    # ai.jobs stores naive UTC; tag it so the response carries an offset.
    return value.replace(tzinfo=timezone.utc) if value is not None else None


async def get_job_stats(db: AsyncSession, window_hours: int) -> JobStatsResponse:
    """Read ai.jobs health directly from the table, as a gauge.

    updated_at is when a row entered its current status (every transition
    writes it), so it is the clock for both the window and the ages.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=window_hours)
    rows = (
        await db.execute(
            select(
                Job.status,
                func.count(),
                func.count().filter(Job.updated_at >= cutoff),
                func.min(Job.updated_at),
            ).group_by(Job.status)
        )
    ).all()
    lifetime = {status: total for status, total, _, _ in rows}
    recent = {status: count for status, _, count, _ in rows}
    oldest = {status: _as_utc(at) for status, _, _, at in rows}

    latest_failure = None
    if lifetime.get("failed"):
        failure = (
            await db.execute(
                select(Job.updated_at, Job.task_type, Job.error_message)
                .where(Job.status == "failed")
                .order_by(Job.updated_at.desc().nulls_last(), Job.id.desc())
                .limit(1)
            )
        ).one()
        latest_failure = LatestJobFailure(
            failed_at=_as_utc(failure.updated_at),
            task_type=failure.task_type,
            error_message=(
                scrub_text(failure.error_message)
                if failure.error_message is not None
                else None
            ),
        )

    return JobStatsResponse(
        window_hours=window_hours,
        lifetime=JobStatusCounts(**lifetime),
        recent=JobStatusCounts(**recent),
        oldest_queued_at=oldest.get("queued"),
        oldest_processing_at=oldest.get("processing"),
        oldest_failed_at=oldest.get("failed"),
        latest_failure=latest_failure,
    )
