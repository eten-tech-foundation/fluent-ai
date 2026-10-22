from datetime import datetime

from pydantic import BaseModel, Field


class JobStatusCounts(BaseModel):
    queued: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0


class LatestJobFailure(BaseModel):
    failed_at: datetime | None
    task_type: str
    error_message: str | None = Field(
        description="The job's error_message with credential-like values redacted."
    )


class JobStatsResponse(BaseModel):
    """Current health of the ai.jobs pipeline. Never carries job payloads.

    Timestamps are when a row entered its current status, in UTC.
    """

    window_hours: int = Field(description="Size of the `recent` window.")
    lifetime: JobStatusCounts = Field(description="All rows, by current status.")
    recent: JobStatusCounts = Field(
        description="Rows that entered their current status within the window."
    )
    oldest_queued_at: datetime | None
    oldest_processing_at: datetime | None
    oldest_failed_at: datetime | None = Field(
        description="Oldest failure not yet requeued by a re-trigger."
    )
    latest_failure: LatestJobFailure | None
