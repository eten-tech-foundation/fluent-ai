import json

from app.config import Settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.logging.utils import get_logger
from app.schemas.translations import TranslateRequest, TranslationResult

logger = get_logger(__name__)


class TranslationService:
    def __init__(self, settings: Settings, gemini_client: GoogleGeminiClient):
        self.settings = settings
        self.gemini_client = gemini_client

    async def translate_verses(self, request: TranslateRequest) -> TranslationResult:
        logger.info(
            "Generating translations",
            num_context=len(request.context_verses),
            num_targets=len(request.verses_to_translate),
            target_language=request.target_language_name,
        )

        system_instruction = (
            f"You are an expert Bible translator, fluent in biblical languages, English, and {request.target_language_name}. "
            f"Your goal is to translate biblical text with absolute theological accuracy, natural grammatical flow, "
            f"and culturally appropriate honorifics.\n\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"1. You MUST study the <translation_memory> provided in the prompt. This memory contains verses already translated by expert human translators.\n"
            f"2. You must strictly mimic the linguistic style, vocabulary, spelling, and honorific rules demonstrated in the <translation_memory>.\n"
            f"3. If a theological term (e.g., 'God', 'Jesus', 'Lord', 'faith', 'baptize') appears in the source text, look for how it was translated in the memory. Do not invent new terms.\n"
            f"4. Pay strict attention to gender, plurality, and respect markers (honorifics) used in the target language examples."
        )

        # Build context block
        context_block = "<translation_memory>\n"
        for cv in request.context_verses:
            context_block += f"[Verse ID: {cv.verse_id}]\nSource: {cv.source_text}\nTarget: {cv.target_text}\n\n"
        context_block += "</translation_memory>\n\n"

        # Build target block
        target_block = f"Based strictly on the established vocabulary, grammar, and style in the <translation_memory> above, translate the following new verses into {request.target_language_name}.\n\n"
        target_block += "<verses_to_translate>\n"
        for tv in request.verses_to_translate:
            target_block += f"[Verse ID: {tv.verse_id}]\nSource: {tv.source_text}\n\n"
        target_block += "</verses_to_translate>\n\n"

        # Build JSON instruction
        target_block += (
            "Respond ONLY with a valid JSON object matching this schema. Do not include any markdown formatting or extra text.\n"
            "{\n"
            '  "translations": [\n'
            "    {\n"
            '      "verse_id": "...",\n'
            '      "target_text": "..."\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        full_prompt = context_block + target_block

        try:
            response_text = await self.gemini_client.generate_content(
                prompt=full_prompt,
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=TranslationResult,
            )
            parsed_json = json.loads(response_text)
            return TranslationResult.model_validate(parsed_json)

        except Exception as e:
            logger.error(
                "Translation generation failed",
                error=str(e),
                target_language=request.target_language_name,
            )
            raise
