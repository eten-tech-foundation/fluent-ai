"""
tests/test_google_gemini.py — Unit tests for GoogleGeminiClient.

All tests run without a real network call. The google.genai SDK is patched
at the module level so tests remain fast and deterministic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _settings_with_key(
    key: str = "test-api-key",
    model: str = "gemini-2.5-flash-lite",
) -> Settings:
    """Build a minimal Settings instance with Google AI credentials."""
    return Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
        google_ai_api_key=key,
        google_ai_model=model,
    )


# --------------------------------------------------------------------------- #
# Initialization tests
# --------------------------------------------------------------------------- #


@patch("app.core.ai_clients.google_gemini.genai")
def test_client_initializes_with_valid_api_key(mock_genai: MagicMock) -> None:
    """Client constructs a genai.Client with the configured API key."""
    mock_genai.Client.return_value = MagicMock()
    settings = _settings_with_key(key="valid-key", model="gemini-2.5-flash-lite")

    client = GoogleGeminiClient(settings=settings)

    mock_genai.Client.assert_called_once_with(api_key="valid-key")
    assert client._model_name == "gemini-2.5-flash-lite"
    assert client._client is mock_genai.Client.return_value


@patch("app.core.ai_clients.google_gemini.genai")
def test_client_raises_when_api_key_missing(mock_genai: MagicMock) -> None:
    """Client raises ExternalServiceException (502) when API key is not set."""
    settings = _settings_with_key(key="")  # empty string → falsy

    with pytest.raises(ExternalServiceException) as exc_info:
        GoogleGeminiClient(settings=settings)

    assert exc_info.value.code == ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE
    mock_genai.Client.assert_not_called()


# --------------------------------------------------------------------------- #
# generate_content tests
# --------------------------------------------------------------------------- #


@patch("app.core.ai_clients.google_gemini.genai")
@pytest.mark.asyncio
async def test_generate_content_returns_text(mock_genai: MagicMock) -> None:
    """generate_content() returns the text field from the SDK response."""
    mock_response = MagicMock()
    mock_response.text = "Bonjour le monde"

    # Build out the async call chain: client.aio.models.generate_content(...)
    mock_aio = MagicMock()
    mock_aio.models.generate_content = AsyncMock(return_value=mock_response)
    mock_inner_client = MagicMock()
    mock_inner_client.aio = mock_aio
    mock_genai.Client.return_value = mock_inner_client

    client = GoogleGeminiClient(settings=_settings_with_key())
    result = await client.generate_content("Hello world")

    assert result == "Bonjour le monde"
    mock_aio.models.generate_content.assert_awaited_once_with(
        model="gemini-2.5-flash-lite",
        contents="Hello world",
    )


@patch("app.core.ai_clients.google_gemini.genai")
@pytest.mark.asyncio
async def test_generate_content_raises_on_sdk_error(mock_genai: MagicMock) -> None:
    """SDK exception is caught and re-raised as ExternalServiceException with 502."""
    mock_aio = MagicMock()
    mock_aio.models.generate_content = AsyncMock(
        side_effect=RuntimeError("quota exceeded")
    )
    mock_inner_client = MagicMock()
    mock_inner_client.aio = mock_aio
    mock_genai.Client.return_value = mock_inner_client

    client = GoogleGeminiClient(settings=_settings_with_key())

    with pytest.raises(ExternalServiceException) as exc_info:
        await client.generate_content("translate this")

    assert exc_info.value.code == ErrorCode.EXTERNAL_SERVICE_ERROR
    assert isinstance(exc_info.value.details, dict)
    assert "quota exceeded" in exc_info.value.details.get("error", "")
