"""
core/ai_clients/google_gemini.py — Google Gemini API client.

Wraps the google.genai SDK (google-genai package) to provide a simple async
interface for content generation.
"""

from google import genai

from app.config import Settings
from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException


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

    async def generate_content(self, prompt: str) -> str:
        """Send a prompt to Gemini and return the text response.

        Raises:
            ExternalServiceException: If the SDK raises any error.
        """
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
            )
            return response.text or ""
        except Exception as exc:
            raise ExternalServiceException(
                message="Google Gemini API request failed.",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"error": str(exc)},
            ) from exc
