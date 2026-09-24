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

import re

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse

from app.dependencies import get_tts_service, require_api_key
from app.errors.codes import ErrorCode
from app.errors.exceptions import NotFoundException
from app.models.api_key import ApiKey
from app.schemas.tts import (
    FORMAT_EXTENSIONS,
    STREAMING_EXTENSION,
    TtsGenerateRequest,
    TtsGenerateResponse,
)
from app.services.tts.service import AudioRedirect, TtsService


router = APIRouter()


_SERVED_EXTENSIONS = (STREAMING_EXTENSION, *sorted(set(FORMAT_EXTENSIONS.values())))

_AUDIO_FILE_PATTERN = re.compile(
    rf"^([0-9a-f]{{64}})\.(?:{'|'.join(_SERVED_EXTENSIONS)})$"
)
"""`{hash}.wav`, `{hash}.ogg` or `{hash}.mp3` — resolved by **hash alone**.

64 lowercase hex is exactly what HMAC-SHA256 produces (§9.1), so anything else
cannot name an artifact this service could ever have authorized. Checked here
rather than by a path-parameter pattern so a malformed name answers **404** —
the vocabulary fluent-web's failure classifier already speaks (§6.1) — instead
of a 422 it would have to learn.

The extension is **not** part of the lookup, and is not content negotiation:
`format` is inside the hash, so one hash resolves to exactly one artifact and
the suffix only says which representation era the caller expected (§7.2). All
three are accepted because fluent-api's path validator relays all three; taking
only `.wav` here would turn its defensive breadth into a mystery 404 that no
test on either side covers. Nothing generates the compressed spellings today —
`generate` answers `.wav`, and the 302 points at R2's public domain, not here.
"""

STREAMING_CACHE_CONTROL = "private, max-age=60"
"""Streaming era caching (§7.2).

`private` keeps shared and edge caches out of a URL whose representation
changes when compression finishes; the modest max-age lets one browser replay a
*completed* stream it already paid for. Caches store only complete responses, so
an aborted failure stream (§7.2.1) excludes itself from every layer — which is
one more reason abort-not-EOF is the right failure signal.
"""


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


@router.api_route(
    "/audio/{file}",
    # GET *and* HEAD, spelled out because FastAPI does not do what Starlette
    # does: a bare `@router.get` builds an APIRoute whose method set is exactly
    # {"GET"}, so a HEAD probe would answer 405. fluent-api forwards HEAD as
    # HEAD on purpose (it has a test pinning that), and fluent-web's entire
    # failure-recovery ladder is HEAD probes against this route — 405 would
    # collapse all of it into "unknown error".
    methods=["GET", "HEAD"],
    summary="Stream or redirect to synthesized audio",
    response_class=StreamingResponse,
    responses={
        200: {"description": "Live WAV stream (chunked, no Content-Length)."},
        302: {"description": "Compressed artifact exists; redirect to R2."},
        404: {"description": "No request sidecar — generate was never called."},
        503: {"description": "Admission refused; carries Retry-After."},
    },
)
async def read_tts_audio(
    request: Request,
    file: str,
    service: TtsService = Depends(get_tts_service),
    _: ApiKey = Depends(require_api_key),
):
    """Serve one artifact through the waterfall (§7.2).

    Two response shapes, one URL. During the generation era `{hash}.wav`
    streams live from the heap buffer; once the compressed artifact exists the
    same path answers `302` (never `301` — T22: the `.wav` URL means "whatever
    representation era this artifact is in right now", and a cached permanent
    redirect would freeze that).

    **HEAD is answered without a body, deliberately.** fluent-web classifies
    every playback failure by HEAD-probing this exact URL — 503 ⇒ wait out
    `Retry-After`, 302 ⇒ the compressed object now exists, 404 ⇒ re-run
    generate, 200 ⇒ still streaming (§6.1) — and it is polled during
    wait-for-compressed recovery. Returning a streaming body here would attach
    a reader for the clip's whole duration to a request that discards every
    byte. The probe still runs the full waterfall, including spawning a
    generation on rung 3: that is what makes "200 ⇒ still streaming" true, and
    the cost is bounded, since every later probe attaches to the entry the
    first one created.
    """
    match = _AUDIO_FILE_PATTERN.match(file)
    if match is None:
        raise NotFoundException(
            message=f"'{file}' is not an artifact name.",
            code=ErrorCode.TTS_ARTIFACT_NOT_FOUND,
        )

    resolution = await service.resolve_audio(match.group(1))

    if isinstance(resolution, AudioRedirect):
        return RedirectResponse(resolution.location, status_code=status.HTTP_302_FOUND)

    headers = {
        "Cache-Control": STREAMING_CACHE_CONTROL,
        # Said out loud rather than left to inference: the streaming era has no
        # Content-Length to range into, and a client that assumed otherwise
        # would ask for bytes nobody can supply yet (§7.2).
        "Accept-Ranges": "none",
    }
    if request.method == "HEAD":
        return Response(
            status_code=status.HTTP_200_OK, media_type="audio/wav", headers=headers
        )

    return StreamingResponse(
        resolution.reader(),
        media_type="audio/wav",
        headers=headers,
    )
