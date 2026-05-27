"""internal/project.py — read-only ORM model for public.projects.

Schema: public (owned by fluent-platform, NOT this service).
Access: SELECT only — ai_user has role_ai_reader on the public schema.
        No INSERT / UPDATE / DELETE.
Base:   ExternalBase (from app.db.base) — excluded from Alembic metadata.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ExternalBase


class Project(ExternalBase):
    """Read-only view of public.projects.

    Owned and written by fluent-platform. The AI service only reads.
    """

    __tablename__ = "projects"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_language: Mapped[int] = mapped_column(Integer, nullable=False)
    target_language: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organization: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'not_assigned'")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r} status={self.status!r}>"
