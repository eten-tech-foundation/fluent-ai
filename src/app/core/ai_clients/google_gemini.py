"""
core/ai_clients/google_gemini.py — Google Gemini API client.

Wraps the google.genai SDK (google-genai package) to provide a simple async
interface for content generation.
"""

from google import genai
from google.genai import types

from app.config import Settings
from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException
from app.logging.utils import get_logger

logger = get_logger(__name__)


class GoogleGeminiClient:
    """Async client for the Google Gemini generative AI API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.google_ai_api_key:
            raise ExternalServiceException(
                message="Google AI API key is not configured.",
                code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
            )

        self._model_name = settings.google_ai_model
        self._client = genai.Client(api_key=settings.google_ai_api_key)

    async def generate_content(
        self,
        prompt: str,
        system_instruction: str | None = None,
        response_mime_type: str | None = None,
        response_schema: type | None = None,
    ) -> str:
        """Send a prompt to Gemini and return the text response.

        Args:
            response_schema: Optional Pydantic model class describing the
                expected JSON shape. When set alongside
                response_mime_type="application/json", the SDK validates
                and structures the model's output server-side, removing
                the need for manual fence-stripping/json.loads downstream.

        Raises:
            ExternalServiceException: If the SDK raises any error.
        """
        try:
            config = None
            if system_instruction or response_mime_type or response_schema:
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type=response_mime_type,
                    response_schema=response_schema,
                )

            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=config,
            )
            return response.text or ""
        except Exception as exc:
            logger.error(f"Gemini API call failed: {exc}", exc_info=True)
            raise ExternalServiceException(
                message="Google Gemini API request failed.",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"error": str(exc)},
            ) from exc
