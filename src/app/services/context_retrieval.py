from typing import List, Dict, Any
from sqlalchemy import select, and_, not_, case, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.logging.utils import get_logger
from app.internal.models import Project, ProjectUnit, BibleText, TranslatedVerse, Book
from app.core.bible_metadata import get_context_book_codes

logger = get_logger(__name__)

class ContextVerse:
    def __init__(self, bible_text_id: int, book_code: str, chapter_number: int, verse_number: int, source_text: str, target_text: str):
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
            "target_text": self.target_text
        }

async def get_context_verses_for_prompt(
    db: AsyncSession,
    project_unit_id: int,
    bible_id: int,
    target_book_code: str,
    target_chapter_number: int,
    target_verse_number: int,
    limit: int = 100
) -> List[ContextVerse]:
    try:
        # 1. Find project languages
        stmt = select(Project.source_language, Project.target_language).\
            join(ProjectUnit, ProjectUnit.project_id == Project.id).\
            where(ProjectUnit.id == project_unit_id).\
            limit(1)
        
        result = await db.execute(stmt)
        project_langs = result.first()
        
        if not project_langs:
            logger.error(f"Could not find languages for projectUnitId {project_unit_id}")
            return []
            
        source_lang, target_lang = project_langs

        # 2. Get prioritized book codes
        prioritized_codes = get_context_book_codes(target_book_code)
        
        # Create case statement for ordering by book priority
        whens = {code: idx for idx, code in enumerate(prioritized_codes)}
        book_priority = case(whens, value=Book.code, else_=999)

        # 3. Query similar verses
        query = select(
            BibleText.id.label("bible_text_id"),
            Book.code.label("book_code"),
            BibleText.chapter_number,
            BibleText.verse_number,
            BibleText.text.label("source_text"),
            TranslatedVerse.content.label("target_text")
        ).select_from(TranslatedVerse).\
        join(BibleText, TranslatedVerse.bible_text_id == BibleText.id).\
        join(Book, BibleText.book_id == Book.id).\
        join(ProjectUnit, TranslatedVerse.project_unit_id == ProjectUnit.id).\
        join(Project, ProjectUnit.project_id == Project.id).\
        where(
            and_(
                Project.target_language == target_lang,
                Project.source_language == source_lang,
                TranslatedVerse.content != None,
                TranslatedVerse.content != '',
                not_(and_(
                    Book.code == target_book_code,
                    BibleText.chapter_number == target_chapter_number,
                    BibleText.verse_number == target_verse_number
                ))
            )
        ).\
        order_by(
            book_priority,
            case(
                (TranslatedVerse.project_unit_id == project_unit_id, 0),
                else_=1
            ),
            func.abs(BibleText.chapter_number - target_chapter_number).asc(),
            func.abs(BibleText.verse_number - target_verse_number).asc()
        ).\
        limit(limit)

        result = await db.execute(query)
        rows = result.all()
        
        return [
            ContextVerse(
                row.bible_text_id,
                row.book_code,
                row.chapter_number,
                row.verse_number,
                row.source_text,
                row.target_text
            ) for row in rows
        ]

    except Exception as e:
        logger.error(f"Unexpected Error retrieving context verses: {e}")
        return []
