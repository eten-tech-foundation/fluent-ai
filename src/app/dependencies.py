# dependencies.py — shared FastAPI Depends() callables
#
# This is the single place where cross-cutting concerns are expressed as
# FastAPI dependencies. Routers import from here, not from security/ or db/
# directly, so swapping implementations only requires changing this file.
#
# Active dependencies (import and use these in routers):
#   - get_db                       → yields an AsyncSession per request
#   - require_api_key              → validates X-API-Key header, returns ApiKey record
#   - require_admin                → extends require_api_key, checks "admin" permission
#   - get_google_gemini_client     → returns cached GoogleGeminiClient singleton
#   - GoogleGeminiDep              → Annotated shorthand for Depends(get_google_gemini_client)
#   - get_repeated_words_service   → returns the lifespan-loaded RepeatedWordsService
#   - get_tts_service              → returns the cached TtsService singleton
#   - peek_tts_service             → that singleton if it exists, else None (shutdown)
#
# Example router usage:
#   from app.dependencies import get_db, require_api_key
#   @router.get("/")
#   async def list_items(db: AsyncSession = Depends(get_db), _=Depends(require_api_key)):
#       ...

from typing import Annotated

from fastapi import Depends, Request

from app.config import get_settings
from app.core.ai_clients.google_gemini import GoogleGeminiClient
from app.database import get_db  # noqa: F401 — re-exported for routers
from app.security.auth import require_admin, require_api_key  # noqa: F401
from app.services.greek_room.repeated_words import RepeatedWordsService
from app.services.tts.artifacts import build_artifact_store
from app.services.tts.gemini_provider import GeminiTtsProvider
from app.services.tts.service import TtsService


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


# --------------------------------------------------------------------------- #
# Tool service providers
# --------------------------------------------------------------------------- #


_tts_service: TtsService | None = None


def get_tts_service() -> TtsService:
    """Return the cached TtsService, building it (and its R2 client) on demand.

    Built lazily rather than in `lifespan` on purpose: a deployment with no TTS
    configuration must still boot and serve everything else, so a missing
    bucket or hash secret has to surface as a 503 on TTS routes only — see
    `build_artifact_store`. Nothing is cached on the failure path, so filling in
    the configuration and retrying works without a restart of this dependency's
    memoization.

    Tests swap a fake via `app.dependency_overrides[get_tts_service]`.
    """
    global _tts_service
    if _tts_service is None:
        settings = get_settings()
        _tts_service = TtsService(
            settings=settings,
            store=build_artifact_store(settings),
            # The key is handed over, not read from settings inside the
            # provider, and the SDK client is built on first synthesis: a
            # deployment with no Google key still boots and still authorizes
            # recipes, and only the generation task fails.
            provider=GeminiTtsProvider(api_key=settings.google_ai_api_key),
        )
    return _tts_service


def peek_tts_service() -> TtsService | None:
    """Return the TtsService **only if one was ever built** — never build one.

    Shutdown's handle on the process's generation heap (§8.3). It has to be a
    peek and not `get_tts_service()`: building a service at teardown would
    construct an R2 client for a process that is going away, and — on a
    deployment with no TTS configuration — would raise a 503 out of the
    lifespan, turning a clean shutdown into a crash on a service that had never
    synthesized anything.

    Note for tests: a suite that swaps a fake through
    `app.dependency_overrides[get_tts_service]` never populates this global, so
    lifespan cancellation is a no-op there. That is why the cancellation itself
    is tested against the heap and the service directly, and only the wiring is
    tested through the app.
    """
    return _tts_service


def get_repeated_words_service(request: Request) -> RepeatedWordsService:
    """Return the RepeatedWordsService instance stashed on app.state by lifespan.

    Tests can swap a stub via `app.dependency_overrides[get_repeated_words_service]`.
    """
    return request.app.state.repeated_words_service


__all__ = [
    "get_db",
    "require_api_key",
    "require_admin",
    "get_google_gemini_client",
    "GoogleGeminiDep",
    "get_repeated_words_service",
    "get_tts_service",
    "peek_tts_service",
]
