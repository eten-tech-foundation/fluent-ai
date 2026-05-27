"""internal/platform_models.py — Read-only ORM models for public schema tables.

Schema: public (owned by fluent-platform, NOT this service).
Access: SELECT only — ai_user has role_ai_reader on the public schema.
        No INSERT / UPDATE / DELETE.
Base:   ExternalBase (from app.db.base) — excluded from Alembic metadata.
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ExternalBase


class ProjectUnit(ExternalBase):
    """Read-only view of public.project_units."""

    __tablename__ = "project_units"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)


class BibleText(ExternalBase):
    """Read-only view of public.bible_texts.

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


class TranslatedVerse(ExternalBase):
    """Read-only view of public.translated_verses.

    Contains human-translated verse content. Used by context retrieval
    to build Translation Memory pairs for the AI prompt.
    """

    __tablename__ = "translated_verses"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_unit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bible_text_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)


class Book(ExternalBase):
    """Read-only view of public.books."""

    __tablename__ = "books"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)


class Language(ExternalBase):
    """Read-only view of public.languages.

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
