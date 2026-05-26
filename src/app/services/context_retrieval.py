"""
context_retrieval.py — Hybrid context retrieval for Translation Memory prompts.

When the AI generates a translation suggestion for a verse, it needs
examples of previously translated verses to maintain consistent
vocabulary and style. This module retrieves those examples using a
two-phase "Hybrid Search":

Phase A — FTS (Full Text Search) Lexical Similarity:
    Finds verses that share the same words as the target verse.
    Uses Postgres's to_tsvector/plainto_tsquery with a dynamically
    resolved FTS configuration based on the project's source language.
    Supported languages use stemmed search (e.g., 'english' reduces
    "running" → "run"). Unsupported languages (Gujarati, niche African
    languages) fall back to the 'simple' config (tokenize + lowercase).

Phase B — Stylistic & Geographic Proximity:
    Fills remaining context slots with verses from stylistically
    similar Bible books (e.g., Gospels together, Pauline epistles
    together) and nearby chapters/verses. Prioritizes verses from
    the same project unit.

The combined result is a list of (source_text, target_text) pairs
that get formatted as <translation_memory> in the LLM prompt.
"""

from typing import List
from sqlalchemy import select, and_, not_, case, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.utils import get_logger
from app.internal.platform_models import BibleText, Book, Language, ProjectUnit, TranslatedVerse
from app.internal.project import Project
from app.core.bible_metadata import get_context_book_codes
from app.core.constants import MAX_CONTEXT_VERSES_FTS

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# FTS Configuration Resolver
#
# Maps ISO 639-3 language codes to Postgres text search configurations.
# Postgres ships with built-in dictionaries for ~30 languages. For any
# language not in this map (like 'guj' for Gujarati or niche African
# languages), we fall back to 'simple' which does whitespace tokenization
# and lowercasing without stemming — still effective for exact word matching.
# ---------------------------------------------------------------------------
POSTGRES_FTS_LANGUAGES = {
    "eng": "english",
    "en": "english",
    "spa": "spanish",
    "es": "spanish",
    "fre": "french",
    "fra": "french",
    "fr": "french",
    "ger": "german",
    "deu": "german",
    "de": "german",
    "ita": "italian",
    "it": "italian",
    "por": "portuguese",
    "pt": "portuguese",
    "rus": "russian",
    "ru": "russian",
    "hin": "simple",  # Hindi — no Postgres stemmer
    "guj": "simple",  # Gujarati
    "mar": "simple",  # Marathi
    "ben": "simple",  # Bengali
    "tam": "simple",  # Tamil
}


def get_fts_config(language_code: str | None) -> str:
    """
    Resolve the Postgres FTS configuration for a given language code.
    Returns 'simple' for unsupported or unknown languages.
    """
    if not language_code:
        return "simple"
    return POSTGRES_FTS_LANGUAGES.get(language_code.lower(), "simple")


class ContextVerse:
    """
    A single source-target verse pair used as context in the
    Translation Memory prompt.
    """

    def __init__(
        self,
        bible_text_id: int,
        book_code: str,
        chapter_number: int,
        verse_number: int,
        source_text: str,
        target_text: str,
    ):
        self.bible_text_id = bible_text_id
        self.book_code = book_code
        self.chapter_number = chapter_number
        self.verse_number = verse_number
        self.source_text = source_text
        self.target_text = target_text

    def to_dict(self):
        return {
            "verse_id": f"{self.book_code}_{self.chapter_number}_{self.verse_number}",
            "source_text": self.source_text,
            "target_text": self.target_text,
        }


async def get_context_verses_for_prompt(
    db: AsyncSession,
    project_unit_id: int,
    bible_id: int,
    target_book_code: str,
    target_chapter_number: int,
    target_verse_number: int,
    limit: int = 100,
) -> List[ContextVerse]:
    """
    Retrieve context verses for a Translation Memory prompt using
    a hybrid FTS + proximity search strategy.

    Args:
        db: Async database session.
        project_unit_id: The project unit containing the assignment.
        bible_id: The Bible containing the source text.
        target_book_code: Book code of the verse being translated (e.g., 'mat').
        target_chapter_number: Chapter number of the verse being translated.
        target_verse_number: Verse number of the verse being translated.
        limit: Maximum total context verses to return.

    Returns:
        List of ContextVerse objects (FTS matches first, then proximity).
    """
    try:
        # ------------------------------------------------------------------
        # Step 1: Look up project's source and target language IDs
        # ------------------------------------------------------------------
        stmt = (
            select(Project.source_language, Project.target_language, Project.organization)
            .join(ProjectUnit, ProjectUnit.project_id == Project.id)
            .where(ProjectUnit.id == project_unit_id)
            .limit(1)
        )
        result = await db.execute(stmt)
        project_langs = result.first()

        if not project_langs:
            logger.error(
                f"Could not find languages for projectUnitId {project_unit_id}"
            )
            return []

        source_lang_id, target_lang_id, organization_id = project_langs

        # ------------------------------------------------------------------
        # Step 2: Resolve source language code for dynamic FTS configuration
        # ------------------------------------------------------------------
        lang_stmt = (
            select(Language.lang_code_iso_639_3)
            .where(Language.id == source_lang_id)
            .limit(1)
        )
        lang_result = await db.execute(lang_stmt)
        source_lang_code = lang_result.scalar_one_or_none()
        fts_config = get_fts_config(source_lang_code)

        logger.info(
            f"Resolved source language code '{source_lang_code}' "
            f"to FTS config '{fts_config}'"
        )

        # ------------------------------------------------------------------
        # Step 3: Get the source text of the verse being translated
        # (needed as the FTS search query)
        # ------------------------------------------------------------------
        target_verse_stmt = (
            select(BibleText.text)
            .join(Book, BibleText.book_id == Book.id)
            .where(
                BibleText.bible_id == bible_id,
                Book.code == target_book_code.upper(),
                BibleText.chapter_number == target_chapter_number,
                BibleText.verse_number == target_verse_number,
            )
        )
        tv_result = await db.execute(target_verse_stmt)
        target_text = tv_result.scalar_one_or_none()

        # ------------------------------------------------------------------
        # Step 4A: FTS Lexical Similarity Search
        # Find translated verses whose source text shares vocabulary
        # with the verse being translated.
        # ------------------------------------------------------------------
        fts_rows = []
        if target_text:
            # Build the FTS match expression using SQLAlchemy's func
            # to avoid raw SQL string interpolation issues.
            fts_match_expr = func.to_tsvector(fts_config, BibleText.text).op("@@")(
                func.plainto_tsquery(fts_config, target_text)
            )

            fts_query = (
                select(
                    BibleText.id.label("bible_text_id"),
                    Book.code.label("book_code"),
                    BibleText.chapter_number,
                    BibleText.verse_number,
                    BibleText.text.label("source_text"),
                    TranslatedVerse.content.label("target_text"),
                )
                .select_from(TranslatedVerse)
                .join(BibleText, TranslatedVerse.bible_text_id == BibleText.id)
                .join(Book, BibleText.book_id == Book.id)
                .join(ProjectUnit, TranslatedVerse.project_unit_id == ProjectUnit.id)
                .join(Project, ProjectUnit.project_id == Project.id)
                .where(
                    and_(
                        Project.target_language == target_lang_id,
                        Project.source_language == source_lang_id,
                        Project.organization == organization_id,
                        BibleText.bible_id == bible_id,
                        TranslatedVerse.content != None,
                        TranslatedVerse.content != "",
                        # Exclude the verse we are about to translate
                        not_(
                            and_(
                                Book.code == target_book_code.upper(),
                                BibleText.chapter_number == target_chapter_number,
                                BibleText.verse_number == target_verse_number,
                            )
                        ),
                        fts_match_expr,
                    )
                )
                .order_by(
                    func.ts_rank(
                        func.to_tsvector(fts_config, BibleText.text),
                        func.plainto_tsquery(fts_config, target_text),
                    ).desc()
                )
                .limit(MAX_CONTEXT_VERSES_FTS)
            )

            fts_result = await db.execute(fts_query)
            fts_rows = fts_result.all()

        fts_bible_text_ids = [row.bible_text_id for row in fts_rows]

        # ------------------------------------------------------------------
        # Step 4B: Stylistic & Geographic Proximity Search
        # Fill remaining context slots with verses from similar Bible
        # books and nearby chapters, excluding FTS matches.
        # ------------------------------------------------------------------
        prox_limit = limit - len(fts_rows)
        prox_rows = []

        if prox_limit > 0:
            prioritized_codes = get_context_book_codes(target_book_code)
            whens = {code.upper(): idx for idx, code in enumerate(prioritized_codes)}
            book_priority = case(whens, value=Book.code, else_=999)

            where_conditions = [
                Project.target_language == target_lang_id,
                Project.source_language == source_lang_id,
                Project.organization == organization_id,
                BibleText.bible_id == bible_id,
                TranslatedVerse.content != None,
                TranslatedVerse.content != "",
                not_(
                    and_(
                        Book.code == target_book_code.upper(),
                        BibleText.chapter_number == target_chapter_number,
                        BibleText.verse_number == target_verse_number,
                    )
                ),
            ]
            # Exclude verses already found by FTS to avoid duplicates
            if fts_bible_text_ids:
                where_conditions.append(BibleText.id.notin_(fts_bible_text_ids))

            prox_query = (
                select(
                    BibleText.id.label("bible_text_id"),
                    Book.code.label("book_code"),
                    BibleText.chapter_number,
                    BibleText.verse_number,
                    BibleText.text.label("source_text"),
                    TranslatedVerse.content.label("target_text"),
                )
                .select_from(TranslatedVerse)
                .join(BibleText, TranslatedVerse.bible_text_id == BibleText.id)
                .join(Book, BibleText.book_id == Book.id)
                .join(ProjectUnit, TranslatedVerse.project_unit_id == ProjectUnit.id)
                .join(Project, ProjectUnit.project_id == Project.id)
                .where(and_(*where_conditions))
                .order_by(
                    book_priority,
                    # Prefer verses from the same project unit
                    case(
                        (TranslatedVerse.project_unit_id == project_unit_id, 0),
                        else_=1,
                    ),
                    func.abs(BibleText.chapter_number - target_chapter_number).asc(),
                    func.abs(BibleText.verse_number - target_verse_number).asc(),
                )
                .limit(prox_limit)
            )

            prox_result = await db.execute(prox_query)
            prox_rows = prox_result.all()

        # Combine: FTS results first (highest relevance), then proximity
        combined_rows = fts_rows + prox_rows

        return [
            ContextVerse(
                row.bible_text_id,
                row.book_code,
                row.chapter_number,
                row.verse_number,
                row.source_text,
                row.target_text,
            )
            for row in combined_rows
        ]

    except Exception as e:
        logger.error(f"Unexpected Error retrieving context verses: {e}")
        return []
