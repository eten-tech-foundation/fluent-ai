# dependencies.py — shared FastAPI Depends() callables
#
# This is the single place where cross-cutting concerns are expressed as
# FastAPI dependencies. Routers import from here, not from security/ or db/
# directly, so swapping implementations only requires changing this file.
#
# Active dependencies (import and use these in routers):
#   - get_db                    → yields an AsyncSession per request
#   - require_api_key           → validates X-API-Key header, returns ApiKey record
#   - require_admin             → extends require_api_key, checks "admin" permission
#   - get_google_gemini_client  → returns cached GoogleGeminiClient singleton
#   - GoogleGeminiDep           → Annotated shorthand for Depends(get_google_gemini_client)
#
# Example router usage:
#   from app.dependencies import get_db, require_api_key
#   @router.get("/")
#   async def list_items(db: AsyncSession = Depends(get_db), _=Depends(require_api_key)):
#       ...

from typing import Annotated

from fastapi import Depends

from app.config import get_settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.database import get_db  # noqa: F401 — re-exported for routers
from app.security.auth import require_admin, require_api_key  # noqa: F401


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

__all__ = [
    "get_db",
    "require_api_key",
    "require_admin",
    "get_google_gemini_client",
    "GoogleGeminiDep",
]
