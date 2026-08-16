"""
tests/tts/test_real_smoke.py — the opt-in real-infrastructure smoke (phase 09).

**This test spends money and writes to the real bucket.** It is skipped unless
`TTS_SMOKE_REAL=1` (see `conftest.py`), and it is the only test in the repo
that talks to anything outside this process.

    cd fluent-ai
    TTS_SMOKE_REAL=1 uv run pytest tests/tts/test_real_smoke.py -s

`-s` because the run prints a measurement report — first-audio latency,
compression ratio, encoded duration — which is the half of this test a human
reads. The assertions cover the half a machine can check.

── Why one long test instead of several ──────────────────────────────────────
Every run of this file is one Gemini bill. Split into six tests it would be six
bills, or one bill smuggled into a session-scoped fixture whose failure mode is
harder to read than the thing it tidies. So the round trip runs once, in order,
with each stage asserting before the next begins — and the stage names are in
the output so a failure says *where* rather than just "smoke failed".

── What is real here, and what is not ────────────────────────────────────────
Real: Gemini synthesis, the streaming reader, the ffmpeg subprocess, every R2
round trip, and the public custom domain. Faked: the API-key check, because it
validates against a Postgres row and this test has no database — the deployed
container demo covers that hop, and it is not what this file is proving.

The streaming era is measured at the **service** layer rather than through the
ASGI client, because httpx's ASGI transport buffers a whole response (the same
limitation `test_tts_audio.py` documents), which would make a time-to-first-byte
figure a fiction. The compressed era *is* driven through the route, since a
302 arrives whole.

── The trap this test was written around (G4) ────────────────────────────────
`dev.tts.fluent.bible` answers **403 to `Python-urllib`** by User-Agent while
browsers, curl, AVPlayer, ExoPlayer and even an empty UA get 200. A smoke
script that inherits a Python client's default UA can therefore "prove" the
bucket is private when it is not. Every request to the public host below sets
an explicit User-Agent, and that is not cosmetic.
"""

import asyncio
import json
import os
import struct
import subprocess
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from app.config import get_settings
from app.dependencies import get_tts_service, require_api_key
from app.main import app
from app.schemas.tts import FORMAT_CONTENT_TYPES, FORMAT_EXTENSIONS, TtsGenerateRequest
from app.services.tts.artifacts import JSON_CONTENT_TYPE, TtsArtifactStore
from app.services.tts.compression import resolve_ffmpeg_binary
from app.services.tts.gemini_provider import GEMINI_PCM, GeminiTtsProvider
from app.services.tts.recipe import artifact_hash, build_recipe
from app.services.tts.service import AudioStream
from app.services.tts.wav import UNKNOWN_SIZE, WAV_HEADER_BYTES


if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from app.config import Settings


pytestmark = pytest.mark.real_infra


SMOKE_TEXT = "In the beginning God created the heaven and the earth."
"""Genesis 1:1, KJV — public domain, one verse long, and the same sentence the
2026-08-13 provider check spoke aloud, so two clips can be compared by ear."""

SMOKE_USER_AGENT = "fluent-ai-tts-smoke/1.0"
"""Explicit, because the default would be the question (see G4 above)."""

KEEP_ARTIFACTS_ENV_VAR = "TTS_SMOKE_KEEP"
"""Set to `1` to leave the three objects in the bucket after the run.

Default is to delete them, for two reasons: the next run then exercises a cold
artifact (a leftover audio object would redirect on the first listen and the
provider would never be called), and the dev bucket does not accumulate
one-verse debris. Keep them when the point of the run is to demo the
compressed era, or to listen to what `OPUS_BITRATE` actually sounds like.
"""

GENERATION_TIMEOUT_SECONDS = 120.0
"""Ceiling for the whole synthesis, so a hung provider fails the test rather
than the session. Generously above the ~3.6 s a verse took when measured."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _require_real_configuration(settings: "Settings") -> None:
    """Fail loudly, before spending anything, if the environment is incomplete.

    A `fail` and not a `skip`: the run was explicitly opted into, so silently
    passing a smoke that never touched the provider is the one outcome this
    test must not produce.
    """
    missing = [
        name
        for name, value in (
            ("GOOGLE_AI_API_KEY", settings.google_ai_api_key),
            ("R2_ACCOUNT_ID", settings.r2_account_id),
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            ("R2_TTS_BUCKET", settings.r2_tts_bucket),
            ("TTS_HASH_SECRET", settings.tts_hash_secret),
            ("TTS_PUBLIC_AUDIO_BASE_URL", settings.tts_public_audio_base_url),
        )
        if not value
    ]
    if missing:
        pytest.fail(
            "the real smoke needs a fully configured .env; missing: "
            + ", ".join(missing)
        )


def _r2_client(settings: "Settings") -> Any:
    """A raw S3 client for this test's own bookkeeping.

    Built here rather than reached for inside `TtsArtifactStore` because the
    store exposes exactly the four operations the design needs, and `delete` is
    deliberately not one of them (§9.4: artifacts are immutable and there is no
    eviction). A smoke test that creates objects should be able to remove its
    own, without that ability existing in the service.
    """
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _decode_with_ffmpeg(wav: bytes) -> str:
    """Decode the assembled WAV to /dev/null and return ffmpeg's report.

    "The stream plays" is the claim §7.2.1 rests on and the one thing a test
    cannot check by looking at bytes. Feeding the exact response body to a
    decoder **on a pipe** is the closest a machine gets: it proves the 44-byte
    header with its two `0xFFFFFFFF` sizes is readable by a player that cannot
    seek, which is precisely the browser's situation during a first listen.
    """
    completed = subprocess.run(
        [
            resolve_ffmpeg_binary(),
            "-hide_banner",
            "-nostdin",
            "-i",
            "pipe:0",
            "-f",
            "null",
            "-",
        ],
        input=wav,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "the streamed WAV did not decode: "
            + completed.stderr.decode("utf-8", "replace")[-2000:]
        )
    return completed.stderr.decode("utf-8", "replace")


def _report(stage: str, **fields: Any) -> None:
    print(f"\n[smoke] {stage}: " + "  ".join(f"{k}={v}" for k, v in fields.items()))


# --------------------------------------------------------------------------- #
# The round trip
# --------------------------------------------------------------------------- #


async def test_a_verse_is_synthesized_streamed_compressed_stored_and_served(
    tmp_path: "Path",
) -> None:
    settings = get_settings()
    _require_real_configuration(settings)

    provider = GeminiTtsProvider(api_key=settings.google_ai_api_key)
    recipe = build_recipe(
        TtsGenerateRequest(text=SMOKE_TEXT), settings=settings, provider=provider
    )
    assert settings.tts_hash_secret is not None  # checked above
    digest = artifact_hash(recipe, secret=settings.tts_hash_secret)

    client = _r2_client(settings)
    store = TtsArtifactStore(
        client=client,
        bucket=settings.r2_tts_bucket or "",
        prefix=settings.tts_r2_prefix,
    )
    keys = {
        "request": store.request_key(digest),
        "audio": store.audio_key(digest, FORMAT_EXTENSIONS[recipe.format]),
        "receipt": store.receipt_key(digest),
    }

    # ---------------------------------------------------------------- #
    # Arrange — start cold, deliberately.
    # ---------------------------------------------------------------- #
    # A leftover audio object from an earlier run would send the first listen
    # straight to rung 2 and the provider would never be called: the test would
    # pass without proving anything it exists to prove. Deleting first is how
    # "cold" stops being an assumption. (Also cleans up after a run that
    # crashed before its own teardown.)
    for key in keys.values():
        client.delete_object(Bucket=settings.r2_tts_bucket, Key=key)
    _report("arrange", artifact=digest[:16] + "…", **keys)

    service = get_tts_service()
    try:
        # ------------------------------------------------------------ #
        # 1. generate — the sidecar lands, no audio is produced (T8).
        # ------------------------------------------------------------ #
        response = await service.generate(TtsGenerateRequest(text=SMOKE_TEXT))
        assert response.audio_url == f"audio/{digest}.wav"

        sidecar_head = await store.head(keys["request"])
        assert sidecar_head is not None, "generate did not write the request sidecar"
        assert sidecar_head.content_type == JSON_CONTENT_TYPE
        sidecar = await store.get_json(keys["request"])
        assert sidecar is not None
        assert sidecar["text"] == SMOKE_TEXT
        assert sidecar["model"] == settings.tts_model
        assert sidecar["format"] == recipe.format
        assert await store.head(keys["audio"]) is None, (
            "generate must never synthesize — an audio object exists already"
        )
        _report("generate", sidecar_bytes=sidecar_head.size_bytes, audio="absent")

        # ------------------------------------------------------------ #
        # 2. First listen — rung 3: spawn, attach, stream (§7.2).
        # ------------------------------------------------------------ #
        started = time.monotonic()
        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream), (
            f"expected a live stream on a cold artifact, got {resolution!r}"
        )
        tail_task = resolution.entry.task

        chunks: list[bytes] = []
        first_byte_seconds: float | None = None
        async with asyncio.timeout(GENERATION_TIMEOUT_SECONDS):
            async for chunk in resolution.reader():
                if first_byte_seconds is None and len(chunk) > WAV_HEADER_BYTES:
                    # The first yield is header+audio, so this is genuinely the
                    # moment a player could start making sound.
                    first_byte_seconds = time.monotonic() - started
                chunks.append(chunk)
        total_seconds = time.monotonic() - started

        wav = b"".join(chunks)
        pcm_bytes = len(wav) - WAV_HEADER_BYTES
        assert first_byte_seconds is not None, "the stream yielded no audio at all"
        assert len(chunks) > 1, (
            "the whole clip arrived in one chunk — this was not a live stream"
        )
        assert first_byte_seconds < total_seconds, (
            "audio was not available before synthesis finished"
        )

        # The header, field by field: a clip that plays at the wrong pitch is
        # exactly what a wrong sample rate here would produce, and no other
        # test in the suite compares it against the provider's real output.
        assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
        assert struct.unpack("<I", wav[4:8])[0] == UNKNOWN_SIZE
        assert struct.unpack("<I", wav[40:44])[0] == UNKNOWN_SIZE
        channels, sample_rate = struct.unpack("<HI", wav[22:28])
        assert (channels, sample_rate) == (
            GEMINI_PCM.channels,
            GEMINI_PCM.sample_rate_hz,
        )

        pcm_seconds = pcm_bytes / GEMINI_PCM.byte_rate
        # Two rates, and only the second one predicts a stall. Dividing the
        # clip by the *whole* elapsed time counts the pre-first-byte wait as if
        # it were slow audio, which reads as "slower than realtime" even when
        # the stream comfortably outruns the player. What matters to a listener
        # who starts playing at the first byte is how fast the REST arrives: at
        # under 1x, playback catches the writer and the stall watchdog (§6.1)
        # takes over; above 1x the clip plays straight through.
        delivery_seconds = total_seconds - first_byte_seconds
        assert delivery_seconds > 0
        _report(
            "stream",
            chunks=len(chunks),
            pcm_bytes=pcm_bytes,
            audio_seconds=round(pcm_seconds, 2),
            first_audio_s=round(first_byte_seconds, 2),
            complete_s=round(total_seconds, 2),
            realtime_x_after_first_byte=round(pcm_seconds / delivery_seconds, 2),
            realtime_x_including_wait=round(pcm_seconds / total_seconds, 2),
        )

        # ------------------------------------------------------------ #
        # 3. The WAV a browser would receive actually decodes.
        # ------------------------------------------------------------ #
        wav_path = tmp_path / f"{digest[:16]}.wav"
        wav_path.write_bytes(wav)
        _decode_with_ffmpeg(wav)
        _report("decode", playable="yes", saved=str(wav_path))

        # ------------------------------------------------------------ #
        # 4. The compression tail — one real transcode through the pipe.
        # ------------------------------------------------------------ #
        # Awaiting the task rather than sleeping: the response ending is not
        # the generation ending, and the tail runs after `complete` (§10.1).
        assert tail_task is not None
        async with asyncio.timeout(GENERATION_TIMEOUT_SECONDS):
            await asyncio.wait([tail_task])

        audio_head = await store.head(keys["audio"])
        assert audio_head is not None, "the compression tail stored no audio object"
        assert audio_head.content_type == FORMAT_CONTENT_TYPES[recipe.format]
        assert audio_head.size_bytes < pcm_bytes, "the 'compressed' clip is not smaller"

        receipt = await store.get_json(keys["receipt"])
        assert receipt is not None, "the tail wrote no receipt"
        assert receipt["size_bytes"] == audio_head.size_bytes
        assert receipt["format"] == recipe.format
        assert receipt["duration_ms"] is not None, (
            "ffmpeg reported no duration; the receipt lost the one number "
            "the compressed container gives away for free"
        )
        # Within a second of the PCM's own arithmetic — the encoder and the
        # byte count disagreeing would mean the header lies about the rate.
        assert abs(receipt["duration_ms"] / 1000 - pcm_seconds) < 1.0

        clip = await store.get_bytes(keys["audio"])
        assert clip is not None
        clip_path = tmp_path / f"{digest[:16]}.{FORMAT_EXTENSIONS[recipe.format]}"
        clip_path.write_bytes(clip)
        _report(
            "tail",
            compressed_bytes=len(clip),
            ratio=f"{pcm_bytes / len(clip):.1f}x",
            duration_ms=receipt["duration_ms"],
            saved=str(clip_path),
        )

        # ------------------------------------------------------------ #
        # 5. Rung 2 over the real route — the same URL now redirects.
        # ------------------------------------------------------------ #
        app.dependency_overrides[require_api_key] = lambda: object()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://ai"
        ) as ai_client:
            redirected = await ai_client.get(f"/tts/audio/{digest}.wav")
            missing = await ai_client.get(f"/tts/audio/{'0' * 64}.wav")

        assert redirected.status_code == 302
        expected = (
            f"{(settings.tts_public_audio_base_url or '').rstrip('/')}/{keys['audio']}"
        )
        assert redirected.headers["location"] == expected
        # Rung 4, free: an unauthorized hash 404s so the client re-generates.
        assert missing.status_code == 404
        _report("route", redirect=redirected.headers["location"], unknown_hash=404)

        # ------------------------------------------------------------ #
        # 6. The public domain serves it — with an explicit UA (G4).
        # ------------------------------------------------------------ #
        async with httpx.AsyncClient(
            headers={"User-Agent": SMOKE_USER_AGENT}, timeout=30.0
        ) as public:
            served = await public.get(expected)

        assert served.status_code == 200, (
            f"the public host answered {served.status_code}; if that is 403, "
            "check the User-Agent before concluding the bucket is private (G4)"
        )
        assert served.content == clip, "the served bytes are not the stored bytes"
        assert served.headers["content-type"] == FORMAT_CONTENT_TYPES[recipe.format]
        _report("public", status=200, bytes=len(served.content))

        summary = {
            "artifact_hash": digest,
            "text_chars": len(SMOKE_TEXT),
            "pcm_bytes": pcm_bytes,
            "audio_seconds": round(pcm_seconds, 3),
            "first_audio_seconds": round(first_byte_seconds, 3),
            "complete_seconds": round(total_seconds, 3),
            "realtime_x_after_first_byte": round(pcm_seconds / delivery_seconds, 2),
            "compressed_bytes": len(clip),
            "compression_ratio": round(pcm_bytes / len(clip), 2),
            "duration_ms": receipt["duration_ms"],
            "format": recipe.format,
            "model": settings.tts_model,
            "voice": settings.tts_voice,
        }
        (tmp_path / "smoke-report.json").write_text(json.dumps(summary, indent=2))
        _report("done", report=str(tmp_path / "smoke-report.json"))

    finally:
        app.dependency_overrides.pop(require_api_key, None)
        if os.getenv(KEEP_ARTIFACTS_ENV_VAR) == "1":
            _report("teardown", kept=", ".join(keys.values()))
        else:
            for key in keys.values():
                client.delete_object(Bucket=settings.r2_tts_bucket, Key=key)
            _report("teardown", deleted=len(keys))
