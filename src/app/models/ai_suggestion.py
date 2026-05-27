"""models/ai_suggestion.py — ORM models for AI suggestion tables.

Schema: ai (owned by this service, Alembic-managed).
Access: full DML — this service creates, updates, and reads suggestion jobs/results.
Base:   OwnedBase (from app.db.base).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OwnedBase


class AiSuggestionJob(OwnedBase):
    """Background job queue for AI translation suggestions.

    Each row represents a request to generate AI translations for a
    contiguous range of verses (verse_start to verse_end).

    Lifecycle: queued → processing → completed | failed
    On transient failures, retry_count is incremented and the job
    is re-queued up to MAX_JOB_RETRIES times.

    Lives in the 'ai' schema — full DML access for ai_user.
    """

    __tablename__ = "ai_suggestion_jobs"
    __table_args__ = (
        Index("idx_ai_suggestion_jobs_status_created", "status", "created_at"),
        Index(
            "idx_ai_suggestion_jobs_dedup",
            "project_unit_id",
            "bible_id",
            "book_code",
            "chapter_number",
        ),
        UniqueConstraint(
            "project_unit_id",
            "bible_id",
            "book_code",
            "chapter_number",
            "verse_start",
            "verse_end",
            name="uq_ai_jobs_range",
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_id: Mapped[int] = mapped_column(Integer, nullable=False)
    book_code: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_start: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_end: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
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
        DateTime, server_default=text("now()")
    )


class AiSuggestion(OwnedBase):
    """Completed AI translation suggestions.

    Each row contains one AI-generated translation for a single verse.
    The client polls these via GET /project-units/{id}/suggestions.

    Lives in the 'ai' schema — full DML access for ai_user.
    """

    __tablename__ = "ai_suggestions"
    __table_args__ = (
        Index("idx_ai_suggestions_lookup", "project_unit_id", "bible_text_id"),
        UniqueConstraint(
            "bible_text_id", "project_unit_id", name="uq_ai_suggestions_per_text_unit"
        ),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_info: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )


class AiSuggestionUsageLog(OwnedBase):
    """Tracks whether an AI suggestion was viewed or used by a user."""

    __tablename__ = "ai_suggestion_usage_log"
    __table_args__ = (
        Index("idx_ai_usage_user", "user_id"),
        Index("idx_ai_usage_project_unit", "project_unit_id"),
        UniqueConstraint("user_id", "bible_text_id", name="uq_ai_usage_user_text"),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    was_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
