from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.dependencies import require_api_key
from app.logging.utils import get_logger
from app.schemas.translations import TranslateRequest, TranslationResult
from app.services.translation_service import TranslationService

logger = get_logger(__name__)

router = APIRouter()


def get_translation_service(
    settings: Settings = Depends(get_settings),
) -> TranslationService:
    gemini_client = GoogleGeminiClient(settings)
    return TranslationService(settings, gemini_client)


@router.post(
    "/translate",
    response_model=TranslationResult,
    summary="Translate verses using Dynamic RAG",
    dependencies=[Depends(require_api_key)],
)
async def translate_verses(
    request: TranslateRequest,
    service: TranslationService = Depends(get_translation_service),
) -> TranslationResult:
    """
    Translates a list of target verses by dynamically leveraging
    provided context verses as translation memory.
    """
    logger.info("Received translation request")
    return await service.translate_verses(request)
