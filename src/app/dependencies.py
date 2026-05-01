"""
dependencies.py — Shared FastAPI dependency functions.
"""
from typing import Annotated

from fastapi import Depends, Header

from app.config import get_settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.errors.codes import ErrorCode
from app.errors.exceptions import AuthenticationException


async def get_token_header(x_token: str = Header(...)) -> None:
    """Validate the X-Token header required by the items router."""
    if x_token != "fake-super-secret-token":
        raise AuthenticationException(
            message="Invalid or missing X-Token header.",
            code=ErrorCode.TOKEN_INVALID,
            details={"header": "X-Token"},
        )


async def get_query_token(token: str | None = None) -> str:
    """Validate a token passed as a query parameter."""
    if not token:
        raise AuthenticationException(
            message="A token query parameter is required.",
            code=ErrorCode.AUTHENTICATION_REQUIRED,
        )
    return token


# --------------------------------------------------------------------------- #
# AI client singletons
# --------------------------------------------------------------------------- #

_google_gemini_client: GoogleGeminiClient | None = None


async def get_google_gemini_client() -> GoogleGeminiClient:
    """Return the cached GoogleGeminiClient singleton, creating it on first call."""
    global _google_gemini_client
    if _google_gemini_client is None:
        _google_gemini_client = GoogleGeminiClient(settings=get_settings())
    return _google_gemini_client


GoogleGeminiDep = Annotated[GoogleGeminiClient, Depends(get_google_gemini_client)]
