# internal/project.py — read-only ORM model for public.projects.
#
# This is the future home of the Project model, once it is extracted from
# app/internal/models.py. Until that migration happens, the live model
# is at app/internal/models.py:Project.
#
# Schema: public (owned by fluent-server, NOT this service)
# Access: SELECT only — ai_user has role_ai_reader on the public schema.
#         No INSERT, UPDATE, or DELETE operations are permitted.
# Base: ExternalBase (from app.db.base) — excluded from Alembic metadata.
#
# Example contents when implemented:
#
#   from __future__ import annotations
#   from datetime import datetime
#   from typing import Any
#
#   from sqlalchemy import Boolean, DateTime, Integer, String, text
#   from sqlalchemy.dialects.postgresql import JSONB
#   from sqlalchemy.orm import Mapped, mapped_column
#
#   from app.db.base import ExternalBase
#
#   class Project(ExternalBase):
#       __tablename__ = "projects"
#       __table_args__ = {"schema": "public"}
#
#       id: Mapped[int] = mapped_column(Integer, primary_key=True)
#       name: Mapped[str] = mapped_column(String(255), nullable=False)
#       source_language: Mapped[int] = mapped_column(Integer, nullable=False)
#       target_language: Mapped[int] = mapped_column(Integer, nullable=False)
#       is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
#       created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
#       organization: Mapped[int] = mapped_column(Integer, nullable=False)
#       status: Mapped[str] = mapped_column(String, nullable=False)
#       metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
#       created_at: Mapped[datetime | None] = mapped_column(DateTime)
#       updated_at: Mapped[datetime | None] = mapped_column(DateTime)
