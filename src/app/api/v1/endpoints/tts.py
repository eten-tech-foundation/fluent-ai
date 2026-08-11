"""
Source-TTS endpoints (source-tts proposal §7.1).

`POST /tts/generate` authorizes and records a synthesis recipe. fluent-api
mirrors it as `POST /ai/tts/generate`, and the audio route that lands with the
serving waterfall (§7.2) must stay its sibling under this same `/tts` prefix —
`generate` answers with a sibling-relative `audio_url`, so the mirror is a
contract requirement on both services, not a convention.

── Why there is no ToolJobResponse envelope here ────────────────────────────
Every other fluent-ai tool answers inside `ToolJobResponse` so a synchronous
tool can later move behind a job queue without a contract change. TTS is not a
tool job: `generate` returns `{audio_url}` and the *audio* is what arrives
asynchronously, over a streaming GET that already has its own lifecycle. Wrapping
it would add an envelope with nothing to say — and fluent-api's client
deliberately bypasses its shared `callFluentAi()` helper for this route because
that helper rebuilds the envelope field by field and would drop `audio_url`.
"""

from fastapi import APIRouter, Depends, status

from app.dependencies import get_tts_service, require_api_key
from app.models.api_key import ApiKey
from app.schemas.tts import TtsGenerateRequest, TtsGenerateResponse
from app.services.tts.service import TtsService


router = APIRouter()


@router.post(
    "/generate",
    response_model=TtsGenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="Authorize and record a text-to-speech synthesis recipe",
)
async def generate_tts(
    payload: TtsGenerateRequest,
    service: TtsService = Depends(get_tts_service),
    _: ApiKey = Depends(require_api_key),
) -> TtsGenerateResponse:
    """Hash the recipe, write its immutable request sidecar, return the URL.

    No audio is produced by this call (T8). Generation is deferred to the first
    `get-audio` for the hash, which is what makes prefetching cheap: fluent-web
    calls this for verses the user may never reach, and an unreached verse costs
    one small R2 PUT and no provider money.

    Repeating the call is an idempotent no-op — the sidecar PUT is conditional —
    so a double-clicked play button or a re-run React effect is harmless.
    """
    return await service.generate(payload)
