"""
models.py — SQLAlchemy models for the Fluent AI service.

This file contains two categories of models:

1. READ-ONLY PLATFORM MODELS (public schema)
   These map to tables owned by the Web API (fluent-server).
   The AI service only has SELECT access via role_ai_reader.
   DO NOT perform INSERT / UPDATE / DELETE on these models.
   Tables: projects, project_units, bible_texts, translated_verses,
           books, languages

2. READ-WRITE AI MODELS (ai schema)
   These are tables owned and managed by the AI service (fluent-ai).
   The AI service has full DML via role_ai_data.
   Tables: ai_suggestion_jobs, ai_suggestions, api_keys
"""

from __future__ import annotations
from datetime import datetime
from typing import Any

import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# =========================================================================
# READ-ONLY PLATFORM MODELS (public schema)
# These tables are owned by fluent-server. AI service has SELECT only.
# =========================================================================


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


class ProjectUnit(Base):
    """Read-only view of public.project_units."""

    __tablename__ = "project_units"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)


class BibleText(Base):
    """
    Read-only view of public.bible_texts.

    Contains the source text of every verse in every uploaded Bible.
    Used by the worker to fetch verses to translate, and by the
    context retrieval service for FTS searches.
    """

    __tablename__ = "bible_texts"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bible_id: Mapped[int] = mapped_column(Integer, nullable=False)
    book_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)


class TranslatedVerse(Base):
    """
    Read-only view of public.translated_verses.

    Contains human-translated verse content. Used by context retrieval
    to build Translation Memory pairs for the AI prompt.
    """

    __tablename__ = "translated_verses"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)


class Book(Base):
    """Read-only view of public.books."""

    __tablename__ = "books"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)


class Language(Base):
    """
    Read-only view of public.languages.

    Used to resolve the source language code for dynamic FTS
    configuration, and to look up the target language name
    for the AI translation prompt.

    Note: The ISO 639-3 code column is named 'lang_code_iso_639_3'
    in the database, not 'code'.
    """

    __tablename__ = "languages"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lang_name: Mapped[str] = mapped_column(String(100), nullable=False)
    lang_code_iso_639_3: Mapped[str | None] = mapped_column(String(3), nullable=True)


# =========================================================================
# READ-WRITE AI MODELS (ai schema)
# These tables are owned by fluent-ai. Full DML via role_ai_data.
# =========================================================================


class ApiKey(Base):
    """
    API key records for authenticating external callers.
    Stored in the ai schema (owned by fluent-ai).
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(owner_user_id, owner_org_id) = 1",
            name="ck_api_keys_single_owner",
        ),
        {"schema": "ai"},
    )

    id: Column = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash: Column = Column(Text, nullable=False, unique=True)
    name: Column = Column(String(255), nullable=False)
    permissions: Column = Column(ARRAY(Text), nullable=False, server_default="{}")
    is_active: Column = Column(Boolean, nullable=False, default=True)
    owner_user_id: Column = Column(Integer, nullable=True)
    owner_org_id: Column = Column(Integer, nullable=True)
    created_at: Column = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    expires_at: Column = Column(DateTime(timezone=True), nullable=True)


class AiSuggestionJob(Base):
    """
    Background job queue for AI translation suggestions.

    Each row represents a request to generate AI translations for a
    contiguous range of verses (verse_start to verse_end).

    Lifecycle: queued → processing → completed | failed
    On transient failures, retry_count is incremented and the job
    is re-queued up to MAX_JOB_RETRIES times.

    Lives in the 'ai' schema — full DML access for ai_user.
    """

    __tablename__ = "ai_suggestion_jobs"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_id: Mapped[int] = mapped_column(Integer, nullable=False)
    book_code: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_start: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_end: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'queued'"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class AiSuggestion(Base):
    """
    Completed AI translation suggestions.

    Each row contains one AI-generated translation for a single verse.
    The client polls these via GET /project-units/{id}/suggestions.

    Lives in the 'ai' schema — full DML access for ai_user.
    """

    __tablename__ = "ai_suggestions"
    __table_args__ = {"schema": "ai"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_info: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
