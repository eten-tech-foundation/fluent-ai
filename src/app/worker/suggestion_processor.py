import asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.logging.utils import get_logger
from app.internal.models import AiSuggestionJob, AiSuggestion, BibleText
from app.services.context_retrieval import get_context_verses_for_prompt
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.schemas.translations import TranslateRequest, VerseToTranslate
from app.config import get_settings

logger = get_logger(__name__)

async def process_job(db: AsyncSession, job: AiSuggestionJob, gemini_client: GoogleGeminiClient):
    try:
        # Mark as processing
        job.status = 'processing'
        await db.commit()

        # Get verses to translate
        verses_query = select(BibleText).where(
            BibleText.bible_id == job.bible_id,
            BibleText.chapter_number == job.chapter_number,
            BibleText.verse_number >= job.verse_start,
            BibleText.verse_number <= job.verse_end
        )
        verses_result = await db.execute(verses_query)
        verses_to_translate = verses_result.scalars().all()
        
        if not verses_to_translate:
            job.status = 'failed'
            await db.commit()
            return
            
        # Get Context for the first verse in range (simplification)
        context_verses = await get_context_verses_for_prompt(
            db, 
            job.project_unit_id,
            job.bible_id,
            job.book_code,
            job.chapter_number,
            job.verse_start,
            limit=50
        )
        
        request = TranslateRequest(
            target_language_name="Unknown", # Would typically look this up
            context_verses=[cv.to_dict() for cv in context_verses],
            verses_to_translate=[
                VerseToTranslate(
                    verse_id=f"{job.book_code}_{job.chapter_number}_{v.verse_number}",
                    source_text=v.text
                ) for v in verses_to_translate
            ]
        )
        
        # Call AI Service
        result = await gemini_client.translate(request)
        
        # Save results
        for item in result.translations:
            # Match back to bible_text_id
            verse_num = int(item.verse_id.split('_')[-1])
            bible_text = next((v for v in verses_to_translate if v.verse_number == verse_num), None)
            
            if bible_text:
                suggestion = AiSuggestion(
                    bible_text_id=bible_text.id,
                    project_unit_id=job.project_unit_id,
                    suggested_text=item.translated_text,
                    model_info=result.model_used
                )
                db.add(suggestion)
                
        job.status = 'completed'
        await db.commit()
        
    except Exception as e:
        logger.error(f"Error processing job {job.id}: {e}")
        job.status = 'failed'
        await db.commit()

async def worker_loop():
    logger.info("Starting AI Suggestion Worker Loop")
    settings = get_settings()
    gemini_client = GoogleGeminiClient(settings)
    
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # Find queued job
                query = select(AiSuggestionJob).where(AiSuggestionJob.status == 'queued').order_by(AiSuggestionJob.created_at.asc()).limit(1)
                result = await db.execute(query)
                job = result.scalar_one_or_none()
                
                if job:
                    await process_job(db, job, gemini_client)
                else:
                    await asyncio.sleep(5) # Poll every 5 seconds
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(5)
