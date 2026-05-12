"""
models.py — Read-only SQLAlchemy models for the AI service.

These map to tables owned by the Web API (public schema).
The AI service only has SELECT access here via role_ai_reader.
No INSERT / UPDATE / DELETE operations should be performed on these models.
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


class ApiKey(Base):
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
    __tablename__ = "ai_suggestion_jobs"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_id: Mapped[int] = mapped_column(Integer, nullable=False)
    book_code: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_start: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_end: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'queued'"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))

class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_text: Mapped[str] = mapped_column(String, nullable=False)
    model_info: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))

class BibleText(Base):
    __tablename__ = "bible_texts"
    __table_args__ = {"schema": "public"}
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bible_id: Mapped[int] = mapped_column(Integer, nullable=False)
    book_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)

class TranslatedVerse(Base):
    __tablename__ = "translated_verses"
    __table_args__ = {"schema": "public"}
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)

class Book(Base):
    __tablename__ = "books"
    __table_args__ = {"schema": "public"}
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)

class ProjectUnit(Base):
    __tablename__ = "project_units"
    __table_args__ = {"schema": "public"}
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
