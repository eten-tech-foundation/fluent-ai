"""
models.py — Read-only SQLAlchemy models for the AI service.

These map to tables owned by the Web API (public schema).
The AI service only has SELECT access here via role_ai_reader.
No INSERT / UPDATE / DELETE operations should be performed on these models.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    """
    Read-only view of public.projects.

    Owned and written to by fluent-server (web_user / role_web_data).
    The AI service reads this table via role_ai_reader.
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
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'not_assigned'"))
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