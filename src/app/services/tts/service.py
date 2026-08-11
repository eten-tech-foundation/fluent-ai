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

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.errors.codes import ErrorCode
from app.errors.exceptions import ServiceUnavailableException, ValidationException
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
from app.services.tts.recipe import TtsRecipe, artifact_hash, build_recipe


if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings
    from app.services.tts.provider import TtsProvider


logger = get_logger(__name__)


class TtsService:
    """Coordinates identity, storage and (later) generation for one process."""

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
