# src/app/services/tts/gemini_provider.py
"""
Gemini implementation of the TTS provider seam (§8.1, §8.2).

Everything Gemini-specific is meant to be in this file and nowhere else: the
model's SDK types, its event vocabulary, its output format, and its known
glitches. The layers above it see an async iterator of PCM bytes.

── The 2.x Interactions surface, verified live 2026-08-13 ───────────────────
`google-genai` 1.x cannot call this API at all — Google retired the legacy
Interactions wire schema in May 2026 and the server answers `400
invalid_request` — hence the `>=2.0.0` floor in `pyproject.toml`. The 2.x call
shape differs from the proposal's illustrative sketch in four ways, each
confirmed against the real API rather than read off a doc page:

* `speech_config` is **not** a top-level argument; it nests inside
  `generation_config` and is a **list** (the list is what carries
  multi-speaker);
* `response_modalities` is gone, replaced by `response_format={"type": "audio"}`;
* there is no `chunk.audio_bytes` — the stream yields SSE events discriminated
  on `event_type`, and audio rides `step.delta` events whose delta carries
  **base64 text**, so every chunk needs decoding;
* an error can arrive **in-band** as an ordinary `error` event rather than as a
  raised exception, which is why the loop below branches on event type instead
  of iterating to exhaustion.
"""

import base64
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException, ServiceUnavailableException
from app.logging.utils import get_logger
from app.services.tts.provider import PcmFormat, TtsProviderRequest


if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.genai import Client


logger = get_logger(__name__)


GEMINI_PCM = PcmFormat(sample_rate_hz=24000, channels=1, bits_per_sample=16)
"""Raw 24 kHz mono 16-bit PCM (§8.2), re-verified live on 2026-08-13.

The live run observed `audio/l16` at 24000 Hz, 1 channel, in uniform 1920-byte
deltas — 40 ms of audio each, ~25 notifications per second per generation.
"""

_ACCEPTED_MIME_TYPES = frozenset({"audio/l16"})
"""Raw little-endian 16-bit PCM, and nothing else.

Not breadth for its own sake: `audio/wav` would mean the payload carries its own
header, which appended to our streaming header would produce a clip with a
header buried 44 bytes into its audio data. Anything unexpected fails the
generation, which is the tripwire that catches the provider changing format
under us instead of shipping the change to listeners.
"""

_AUDIO_EVENT = "step.delta"
_ERROR_EVENT = "error"


class GeminiTtsProvider:
    """Speech synthesis via Google's Gemini TTS models.

    Satisfies the `TtsProvider` protocol structurally (no inheritance), so the
    protocol stays a description of the seam rather than a base class that
    invites shared implementation.
    """

    def __init__(
        self, *, api_key: str | None = None, client: "Client | None" = None
    ) -> None:
        self._api_key = api_key
        # An already-built client can be handed in, which is how the tests
        # drive real SDK event objects through this loop without a network
        # call — the seam worth faking here is the SDK, not our own parsing.
        self._client = client

    # ------------------------------------------------------------------ #
    # Declarations
    # ------------------------------------------------------------------ #

    def non_byte_affecting_fields(self) -> frozenset[str]:
        """`lang_code` cannot change Gemini's output bytes (T18, K1).

        For Gemini the language hint is advisory: the model infers language
        from the text itself, so `eng`, `en` and an absent value all render the
        same audio. Blanking it out of the recipe means those three requests
        share one artifact and are billed once, while the protocol field stays
        available for a future provider that *does* use it — such a provider
        just omits it from this set.
        """
        return frozenset({"lang_code"})

    def pcm_format(self) -> PcmFormat:
        """What every audio delta must contain, and what the WAV header says."""
        return GEMINI_PCM

    # ------------------------------------------------------------------ #
    # Synthesis
    # ------------------------------------------------------------------ #

    async def synthesize_stream(
        self, request: TtsProviderRequest
    ) -> AsyncIterator[bytes]:
        """Stream one clip's PCM, decoding and checking every audio delta.

        The loop's shape is the design point: it branches on `event_type`
        explicitly and treats anything it does not recognise as audio as a
        failure. Iterating to exhaustion and appending whatever looked like
        bytes would turn an in-band error — or the model's known habit of
        emitting a stray text token into an audio response (§8.2) — into a
        short clip that gets *stored* as the artifact for this hash, forever.
        A failed generation costs one retry; a stored truncated verse is
        permanent.
        """
        client = self._get_client()
        stream = await client.aio.interactions.create(
            model=request.model,
            input=request.text,
            stream=True,
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": request.voice}]},
        )
        if not hasattr(stream, "__aiter__"):  # pragma: no cover - defensive
            raise self._provider_error(
                "Gemini returned a non-streaming interaction despite stream=True."
            )

        audio_deltas = 0
        # The `hasattr` above is what narrows this away from the SDK's
        # `Interaction | AsyncStream` union — and it is also the honest check:
        # a non-streaming answer to `stream=True` is a provider fault, not a
        # typing inconvenience.
        async for event in stream:
            event_type = getattr(event, "event_type", None)

            if event_type == _ERROR_EVENT:
                # In-band, not raised: the SDK hands this to us as an ordinary
                # iteration value, so a loop that only caught exceptions would
                # read a mid-stream failure as a successful short clip.
                error = getattr(event, "error", None)
                raise self._provider_error(
                    "Gemini reported an error mid-stream.",
                    detail=getattr(error, "message", None) or "unspecified",
                )

            if event_type != _AUDIO_EVENT:
                # Lifecycle chatter (`interaction.created`, `step.start`,
                # `step.stop`, `interaction.completed`, status updates).
                continue

            chunk = self._decode_audio_delta(getattr(event, "delta", None))
            if chunk:
                audio_deltas += 1
                yield chunk

        if audio_deltas == 0:
            # A stream that ends without a single audio delta is a failure, not
            # a silent clip: yielding nothing would be stored as a valid
            # zero-length artifact.
            raise self._provider_error("Gemini produced no audio for this request.")

        logger.info(
            "tts gemini synthesis complete",
            model=request.model,
            voice=request.voice,
            audio_deltas=audio_deltas,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _decode_audio_delta(self, delta: Any) -> bytes:
        """Validate one delta's type and format, then decode its base64 data."""
        delta_type = getattr(delta, "type", None)
        if delta_type != "audio":
            # §8.2's documented glitch: the model occasionally emits text tokens
            # into an audio response. Detectable by *type* rather than guessed
            # at, and treated as a failed generation with no special-casing —
            # the delta type is named in the failure so an operator can see at
            # once if some new benign delta kind has started appearing.
            raise self._provider_error(
                "Gemini emitted a non-audio delta in an audio response.",
                detail=f"delta type {delta_type!r}",
            )

        mime_type = getattr(delta, "mime_type", None)
        sample_rate = getattr(delta, "sample_rate", None)
        channels = getattr(delta, "channels", None)
        expected = GEMINI_PCM
        mismatched = (
            (mime_type is not None and mime_type not in _ACCEPTED_MIME_TYPES)
            or (sample_rate is not None and sample_rate != expected.sample_rate_hz)
            or (channels is not None and channels != expected.channels)
        )
        if mismatched:
            # The WAV header went out before this byte arrived (§7.2.1), so a
            # format change cannot be accommodated — only detected. Failing here
            # is what stops a wrong-pitch clip from being stored as the artifact.
            raise self._provider_error(
                "Gemini's audio format does not match the streamed WAV header.",
                detail=(
                    f"got {mime_type} @ {sample_rate} Hz / {channels}ch, "
                    f"expected audio/l16 @ {expected.sample_rate_hz} Hz / "
                    f"{expected.channels}ch"
                ),
            )

        data = getattr(delta, "data", None)
        if not data:
            return b""
        try:
            return base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as exc:
            raise self._provider_error(
                "Gemini sent an audio delta that is not valid base64."
            ) from exc

    def _get_client(self) -> "Client":
        """Build the SDK client on first use, never at import or boot.

        Same rule as the artifact store: a deployment with no Google key must
        still boot and serve everything else, so a missing key surfaces as a
        failed generation on the TTS path only.
        """
        if self._client is None:
            if not self._api_key:
                raise ServiceUnavailableException(
                    message="Gemini TTS is not configured (no Google AI API key).",
                    code=ErrorCode.TTS_PROVIDER_UNAVAILABLE,
                )
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _provider_error(
        self, message: str, *, detail: str | None = None
    ) -> ExternalServiceException:
        """Build the one exception type this provider fails with.

        502 rather than 503: Gemini answered, it just answered wrongly. The
        text being spoken never appears in the message or the details — this
        travels into logs, and the recipe's text is the content itself.
        """
        logger.error("tts gemini synthesis failed", error=message, detail=detail)
        return ExternalServiceException(
            message=message,
            code=ErrorCode.TTS_PROVIDER_UNAVAILABLE,
            details={"detail": detail} if detail else None,
        )
