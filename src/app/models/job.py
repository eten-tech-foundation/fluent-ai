from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OwnedBase

class Job(OwnedBase):
    """Background job queue for AI translation suggestions.

    Each row represents a generic AI task.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index("idx_jobs_status_created", "status", "created_at"),
        UniqueConstraint("dedup_key", name="uq_jobs_dedup_key"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_jobs_status_valid",
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[Literal["queued", "processing", "completed", "failed"]] = mapped_column(
        String(20), nullable=False, server_default=text("'queued'")
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()"), onupdate=text("now()")
    )
