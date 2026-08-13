# src/app/services/tts/service.py
"""
The request-facing TTS service (proposal §7.1, §9.1, §9.3).

What `generate` does: validate, resolve the recipe, hash it, write the
immutable request sidecar, and hand back the audio URL.

What `generate` deliberately does NOT do, and must never start doing:

* **No synthesis.** Generation is lazy — the first `get-audio` for a hash
  spawns it (T8, §7.2). This is what makes prefetch nearly free: fluent-web
  calls `generate` for verses the user may never reach, and an unreached verse
  costs one small R2 PUT and no provider money at all. A future contributor
  will be tempted to "just synthesize here"; that would bill for audio nobody
  listens to and reintroduce the long request this design removed.
* **No duration.** A streaming first listen has no knowable duration, and the
  compressed container carries the exact value for free afterwards (T22, §6.2).
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Any

from app.errors.codes import ErrorCode
from app.errors.exceptions import (
    ExternalServiceException,
    FluentAIException,
    NotFoundException,
    ServiceUnavailableException,
    ValidationException,
)
from app.logging.utils import get_logger
from app.schemas.tts import (
    FORMAT_CONTENT_TYPES,
    FORMAT_EXTENSIONS,
    STREAMING_EXTENSION,
    TtsGenerateRequest,
    TtsGenerateResponse,
)
from app.services.tts.artifacts import (
    JSON_CONTENT_TYPE,
    TtsArtifactStore,
    serialize_json_body,
)
from app.services.tts.generation import GenerationEntry, GenerationHeap
from app.services.tts.provider import TtsProviderRequest
from app.services.tts.recipe import TtsRecipe, artifact_hash, build_recipe
from app.services.tts.wav import streaming_wav_header


if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterator

    from app.config import Settings
    from app.services.tts.provider import TtsProvider


logger = get_logger(__name__)


def _failure_reason(exc: BaseException) -> str:
    """Reduce a failure to a short, stable string for the entry (§8.3, N1).

    A string and not the exception: an exception carries `__traceback__`, whose
    frames hold the entry, and storing it on the entry is precisely the
    reference cycle the done-callback exists to break.
    """
    if isinstance(exc, FluentAIException):
        return exc.code
    if isinstance(exc, TimeoutError):
        return "TTS_GENERATION_TIMEOUT"
    return type(exc).__name__


@dataclass(frozen=True)
class AudioStream:
    """Rungs 1 and 3: serve this hash live from a generation buffer."""

    entry: GenerationEntry
    header: bytes
    max_seconds: float

    def reader(self) -> "AsyncIterator[bytes]":
        """A fresh reader over the entry, for exactly one HTTP response."""
        return self.entry.read(header=self.header, max_seconds=self.max_seconds)


@dataclass(frozen=True)
class AudioRedirect:
    """Rung 2: the compressed artifact exists; send the client to R2."""

    location: str


AudioResolution = AudioStream | AudioRedirect


class TtsService:
    """Coordinates identity, storage and generation for one process."""

    name = "tts"

    def __init__(
        self,
        *,
        settings: "Settings",
        store: TtsArtifactStore,
        provider: "TtsProvider",
    ) -> None:
        self._settings = settings
        self._store = store
        self._provider = provider
        # Per-process state, which is why fluent-ai must run a single
        # application process (T26, §10.1): with `workers=2` the container
        # really uses twice `TTS_MAX_BUFFERED_BYTES`, and dedup splits across
        # two dicts that cannot see each other.
        self._heap = GenerationHeap(
            max_buffered_bytes=settings.tts_max_buffered_bytes,
            max_clip_bytes=settings.tts_max_clip_bytes,
            admission_wait_seconds=settings.tts_admission_wait_seconds,
            retry_after_seconds=settings.tts_retry_after_seconds,
        )

    @property
    def heap(self) -> GenerationHeap:
        """The generation heap — exposed for admission/accounting assertions."""
        return self._heap

    # ------------------------------------------------------------------ #
    # generate
    # ------------------------------------------------------------------ #

    async def generate(self, request: TtsGenerateRequest) -> TtsGenerateResponse:
        """Authorize and record a synthesis recipe; return its audio URL."""
        self._validate(request)

        recipe = build_recipe(request, settings=self._settings, provider=self._provider)
        artifact = self.artifact_hash(recipe)

        key = self._store.request_key(artifact)
        written = await self._store.put_if_absent(
            key,
            serialize_json_body(recipe.to_sidecar_dict()),
            content_type=JSON_CONTENT_TYPE,
        )

        logger.info(
            "tts generate authorized",
            artifact_hash=artifact,
            # The recipe's `text` is never logged: it is the content itself,
            # can be a whole chapter, and adds nothing an operator needs.
            text_length=len(request.text),
            format=recipe.format,
            sidecar_written=written,
        )

        # Sibling-relative on purpose (§7.1): the caller resolves it against
        # the URL it actually called, so the browser's audio fetch lands on
        # fluent-api and a direct consumer's lands here — with no config for
        # anyone else's public hostname, and no rewriting by the proxy.
        return TtsGenerateResponse(audio_url=f"audio/{artifact}.{STREAMING_EXTENSION}")

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #

    def artifact_hash(self, recipe: TtsRecipe) -> str:
        """HMAC the recipe, refusing to name an artifact without the secret."""
        secret = self._settings.tts_hash_secret
        if not secret:
            raise ServiceUnavailableException(
                message="TTS artifact identity is not configured (no hash secret).",
                code=ErrorCode.TTS_STORAGE_NOT_CONFIGURED,
            )
        return artifact_hash(recipe, secret=secret)

    # ------------------------------------------------------------------ #
    # get-audio — the serving waterfall (§7.2)
    # ------------------------------------------------------------------ #

    async def resolve_audio(self, artifact: str) -> AudioResolution:
        """Resolve one hash through the waterfall, in order (§7.2).

        1. an in-heap generation → attach and stream (this bypasses admission:
           the buffer is already paid for);
        2. the compressed object on R2 → 302 to the immutable public URL;
        3. the request sidecar → admission, a detached generation task, and
           attach as its first reader;
        4. nothing → 404, which the client heals by re-calling `generate`.

        **The sidecar is read before the R2 HEAD**, which is the one place the
        implementation reorders the proposal's prose, for a mechanical reason:
        the compressed object's extension comes from the recipe's `format`, so
        its key is not knowable from the hash alone. Reading the sidecar first
        costs the same two round-trips the proposal budgets, and it makes the
        404 rung answer before anything expensive happens — random-hash probe
        traffic gets one GET and a 404.

        The one behaviour this ordering gives up: a hash whose sidecar was
        deleted but whose audio object survived would 404 instead of
        redirecting. Sidecars are immutable and there is no eviction (§9.4), so
        that state cannot arise; if eviction ever lands, this is one of the
        places to revisit.
        """
        entry = self._heap.get(artifact)
        if entry is not None:
            return self._attach(entry, rung="heap")

        sidecar = await self._store.get_json(self._store.request_key(artifact))
        if sidecar is None:
            raise NotFoundException(
                message="No audio has been authorized for this artifact.",
                code=ErrorCode.TTS_ARTIFACT_NOT_FOUND,
                details={"artifact_hash": artifact},
            )
        recipe = TtsRecipe.from_sidecar_dict(sidecar)

        head = await self._store.head(self.audio_key(artifact, recipe.format))
        if head is not None:
            return AudioRedirect(location=self._public_audio_url(artifact, recipe))

        draining = self._heap.get_draining(artifact)
        if draining is not None:
            # Only reachable while the compressed object is absent — the HEAD
            # above already returned. Once it exists the redirect wins, because
            # R2 brings Range support, a Content-Length, edge caching and about
            # a tenth of the bytes (§9.2).
            return self._attach(draining, rung="draining")

        entry = await self._spawn(artifact, recipe)
        return self._attach(entry, rung="spawned")

    def _attach(self, entry: GenerationEntry, *, rung: str) -> AudioStream:
        """Attach a reader to an entry, or refuse if it has already failed.

        The refusal is §8.3's named case: a generation that failed before its
        reader received any headers surfaces as `502
        TTS_PROVIDER_UNAVAILABLE`, because nothing has been written yet and a
        proper error response is still possible. Once headers are out, the only
        honest signal left is the aborted connection (§7.2.1).
        """
        if entry.state == "failed":
            raise ExternalServiceException(
                message="Audio generation failed for this artifact.",
                code=ErrorCode.TTS_PROVIDER_UNAVAILABLE,
                details={"artifact_hash": entry.artifact},
            )
        logger.info(
            "tts audio attach",
            artifact_hash=entry.artifact,
            rung=rung,
            state=entry.state,
            buffered_bytes=self._heap.buffered_bytes,
        )
        return AudioStream(
            entry=entry,
            header=streaming_wav_header(self._provider.pcm_format()),
            max_seconds=self._settings.tts_reader_max_seconds,
        )

    def _public_audio_url(self, artifact: str, recipe: TtsRecipe) -> str:
        """Compose the immutable public URL the 302 points at (§7.3)."""
        base = self._settings.tts_public_audio_base_url
        if not base:
            # Never emit a 'None'-prefixed URL: a redirect to a nonsense host is
            # a broken clip the client cannot classify, while a 503 is a state
            # it already knows how to wait out.
            raise ServiceUnavailableException(
                message="No public audio base URL is configured for redirects.",
                code=ErrorCode.TTS_STORAGE_NOT_CONFIGURED,
            )
        return f"{base.rstrip('/')}/{self.audio_key(artifact, recipe.format)}"

    # ------------------------------------------------------------------ #
    # Generation — the detached task and its done-callback (§8.3, §9.2)
    # ------------------------------------------------------------------ #

    async def _spawn(self, artifact: str, recipe: TtsRecipe) -> GenerationEntry:
        """Pass admission, register the entry, and start its detached task.

        The task is entry-owned and detached from every request lifecycle. That
        is the whole point: a client that disconnects mid-listen must not
        cancel a generation other listeners are attached to, and Starlette
        cancels anything that runs inside a response generator. (`BackgroundTask`
        was also rejected — it runs only *after* the response completes, which
        is the wrong side of a live stream.)
        """
        entry, created = await self._heap.admit(artifact, recipe)
        if not created:
            # Another request for this hash won the race while this one waited
            # for a slot. Attaching to its entry is the whole point of the
            # dedup guard — one generation, one billing event, two listeners.
            return entry

        entry.task = asyncio.create_task(
            self._generate_into(entry), name=f"tts-generate-{artifact[:12]}"
        )
        entry.task.add_done_callback(partial(self._on_generation_done, entry))
        return entry

    async def _generate_into(self, entry: GenerationEntry) -> None:
        """Synthesize into the entry's buffer, waking readers on every append."""
        recipe = entry.recipe
        request = TtsProviderRequest(
            text=recipe.text,
            # `voice` and `lang_code` are None in the recipe when the provider
            # declared them unable to affect its bytes (§9.1). Falling back to
            # configuration here is exactly why blanking them was safe.
            voice=recipe.voice or self._settings.tts_voice,
            model=recipe.model,
            lang_code=recipe.lang_code,
        )
        ceiling = self._heap.max_clip_bytes
        try:
            async with asyncio.timeout(self._settings.tts_generation_max_seconds):
                async for chunk in self._provider.synthesize_stream(request):
                    if len(entry.buffer) + len(chunk) > ceiling:
                        # Belt-and-braces (§9.2): a stream past the provider's
                        # own output cap means a misbehaving provider, and one
                        # runaway generation must not spend a slot's neighbours'
                        # memory. Aborts through the honest-failure path.
                        raise ExternalServiceException(
                            message="Audio generation exceeded the per-clip limit.",
                            code=ErrorCode.TTS_PROVIDER_UNAVAILABLE,
                            details={"max_clip_bytes": ceiling},
                        )
                    await entry.append(chunk)
            await entry.mark_complete()
        except asyncio.CancelledError:
            # SIGTERM, typically. Readers see abort-not-complete, and the
            # request sidecar on R2 means the restarted process (or any other
            # replica) regenerates on the next request — which is why shutdown
            # needs no drain logic at all (§8.3).
            await entry.mark_failed("cancelled")
            self._heap.discard(entry)
            raise
        except Exception as exc:
            await entry.mark_failed(_failure_reason(exc))
            self._heap.discard(entry)
            raise
        await self._finish_generation(entry)

    async def _finish_generation(self, entry: GenerationEntry) -> None:
        """Run the completed clip's tail, then hand the entry to the drain set.

        **Phase 08 lands the compression tail here** (§10.1): HEAD the target
        object, pipe the buffer through ffmpeg, conditional-PUT the audio, then
        the receipt. Until it does, nothing is ever uploaded, so a second listen
        after this entry drains regenerates from the sidecar — correct, and
        billed twice. That is the known cost of splitting the phases, not a bug
        to work around here.
        """
        self._heap.drain(entry)
        logger.info(
            "tts generation complete",
            artifact_hash=entry.artifact,
            size_bytes=len(entry.buffer),
            buffered_bytes=self._heap.buffered_bytes,
        )

    def _on_generation_done(self, entry: GenerationEntry, task: asyncio.Task) -> None:
        """The done-callback, with all three of its load-bearing duties (N1).

        1. **Retrieve the exception**, so asyncio never reports it as never
           retrieved — which is also the only place a failure inside a detached
           task becomes visible at all.
        2. **Clear `entry.task`.** The retrieved exception's `__traceback__`
           references the coroutine's frame, which holds `entry` as a local, so
           leaving the task attached completes an entry -> task -> traceback ->
           frame -> entry cycle. That cycle would park the buffer's finalizer
           on the cyclic collector instead of prompt refcounting — so admission
           accounting would lag exactly when failed entries pile up, i.e.
           during provider trouble.
        3. **Record failure as a string**, never the exception object: storing
           the exception on the entry recreates the same cycle through the back
           door. `entry.error` was already set to a code string by the task.
        """
        exception = None if task.cancelled() else task.exception()
        entry.task = None
        if exception is not None:
            logger.warning(
                "tts generation task failed",
                artifact_hash=entry.artifact,
                error_type=type(exception).__name__,
                error=str(exception),
                reason=entry.error,
            )

    # ------------------------------------------------------------------ #
    # Validation (T27 — this service owns the length limit)
    # ------------------------------------------------------------------ #

    def _validate(self, request: TtsGenerateRequest) -> None:
        """Reject empty and oversized text, each with its own contract code.

        **fluent-ai is the sole authority on length** (operator decision,
        2026-08-11): fluent-api is a passive proxy and enforces only shape. Two
        services with a same-named limit that must agree is a drift bug waiting
        to happen — set them differently and the effective limit silently
        becomes whichever one the operator did not edit. The cost of one
        internal hop for an oversized body is nil: rejection happens before any
        provider call, so nothing is billed.

        `TTS_MAX_TEXT_LENGTH` is a tripwire against accidental chapter/book
        submission or abuse, not a product limit — legitimate input is
        verse-sized (§7.1).
        """
        if not request.text.strip():
            raise ValidationException(
                message="`text` must contain something to speak.",
                code=ErrorCode.TTS_INVALID_REQUEST,
            )

        max_length = self._settings.tts_max_text_length
        actual_length = len(request.text)
        if actual_length > max_length:
            raise ValidationException(
                message=(
                    f"`text` is {actual_length} characters, which exceeds the "
                    f"configured maximum of {max_length}."
                ),
                code=ErrorCode.TTS_TEXT_TOO_LONG,
                details={"max_length": max_length, "actual_length": actual_length},
            )

    # ------------------------------------------------------------------ #
    # Receipt (§9.3) — written by the compression tail, read by nobody
    # ------------------------------------------------------------------ #

    async def write_receipt(
        self,
        artifact: str,
        *,
        recipe: TtsRecipe,
        duration_ms: int | None,
        size_bytes: int,
    ) -> None:
        """Best-effort metadata write, performed last (§9.3, §10.1).

        Three properties are load-bearing, and all three are about what this is
        *not*:

        * **Not a commit marker.** R2 PUTs are atomic, so the audio object's
          presence is self-certifying; the serving waterfall and the
          compression HEAD check key on the audio object alone. A crash between
          the audio PUT and this one is harmless — the clip plays. Nothing
          load-bearing may ever read a receipt, or this design regains exactly
          the stuck-lock failure mode it was built to avoid.
        * **Not sensitive.** It carries no text and no user identifiers,
          because it is publicly fetchable from the bucket domain.
        * **Not a ledger.** Written once, never updated.

        Failures are logged and swallowed for the same reason: a receipt that
        could fail a request would make a cosmetic write load-bearing.
        """
        body: dict[str, Any] = {
            "recipe_version": recipe.recipe_version,
            "model": recipe.model,
            "voice": recipe.voice,
            "format": recipe.format,
            "content_type": FORMAT_CONTENT_TYPES[recipe.format],
            "duration_ms": duration_ms,
            "size_bytes": size_bytes,
            "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            await self._store.put(
                self._store.receipt_key(artifact),
                serialize_json_body(body),
                content_type=JSON_CONTENT_TYPE,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort by design
            logger.warning(
                "tts receipt write failed; ignoring (receipts are never read)",
                artifact_hash=artifact,
                error=str(exc),
            )

    # ------------------------------------------------------------------ #
    # Keys other phases need
    # ------------------------------------------------------------------ #

    def audio_key(self, artifact: str, recipe_format: str) -> str:
        """Key of the compressed object for a hash, per its format.

        One hash resolves to exactly one object because `format` is inside the
        hash, which is why the extension can be derived rather than negotiated.
        """
        return self._store.audio_key(artifact, FORMAT_EXTENSIONS[recipe_format])
