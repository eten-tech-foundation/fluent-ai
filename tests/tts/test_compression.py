"""
tests/tts/test_compression.py — the ffmpeg encoder itself (§10.1, §10.2).

**These spawn a real ffmpeg**, which is the point: everything else in the suite
fakes this seam, so if nothing exercised the actual command line, a wrong flag
would surface as an unplayable artifact in R2 rather than as a red test. They
stay cheap — the fixtures are fractions of a second of audio.

⚠ **They need an ffmpeg that runs on this machine, and that is not guaranteed
by the dependencies.** `imageio-ffmpeg` ships no musl wheel, so inside the
Alpine container these fall back to whatever is on `PATH` and fail outright if
the image provisions nothing (phase 09, 2026-08-16 — B5's packaging answer is
open again). On an ordinary glibc developer machine the wheel supplies it and
there is nothing to provision.
"""

import asyncio
import math
import os
import shutil
import struct
import tempfile

import pytest

from app.services.tts.compression import (
    CompressionError,
    FfmpegCompressor,
    resolve_ffmpeg_binary,
)
from app.services.tts.provider import PcmFormat


PCM = PcmFormat(sample_rate_hz=24000, channels=1, bits_per_sample=16)


def tone(seconds: float = 0.25, hz: int = 440) -> bytes:
    """Signed 16-bit little-endian mono PCM — what the provider yields.

    A tone rather than noise or zeros: silence compresses to almost nothing and
    would hide a truncation, and a real signal makes the duration assertions
    mean something.
    """
    frames = int(PCM.sample_rate_hz * seconds)
    return b"".join(
        struct.pack(
            "<h", int(12000 * math.sin(2 * math.pi * hz * i / PCM.sample_rate_hz))
        )
        for i in range(frames)
    )


@pytest.fixture
def compressor() -> FfmpegCompressor:
    return FfmpegCompressor(concurrency=1)


class TestEncoding:
    async def test_opus_round_trip_produces_a_real_ogg(self, compressor):
        """The default format, end to end through the real binary."""
        clip = await compressor.compress(
            tone(), pcm_format=PCM, target_format="ogg-opus"
        )

        assert clip.content_type == "audio/ogg"
        assert clip.data[:4] == b"OggS"  # the Ogg page signature
        assert b"OpusHead" in clip.data[:200]

    async def test_mp3_round_trip_produces_a_real_mp3(self, compressor):
        """The fallback format — only sent when a browser cannot play Opus
        (§6.1), so it is the rarer artifact and the easier one to break."""
        clip = await compressor.compress(tone(), pcm_format=PCM, target_format="mp3")

        assert clip.content_type == "audio/mpeg"
        # An MPEG audio frame begins with 11 set bits; LAME also writes an ID3
        # tag first, so accept either opener rather than pinning the layout.
        assert clip.data[:3] == b"ID3" or clip.data[0] == 0xFF

    async def test_compression_actually_compresses(self, compressor):
        """§7.2.1 claims the compressed era is about a tenth of the bytes, and
        that claim is what makes the 302 worth preferring over the buffer."""
        pcm = tone(seconds=1.0)

        clip = await compressor.compress(pcm, pcm_format=PCM, target_format="ogg-opus")

        assert len(clip.data) < len(pcm) / 5

    async def test_the_duration_comes_from_the_encoder_not_from_arithmetic(
        self, compressor
    ):
        """§12.3: the receipt's duration is read off the produced container.

        Sourced from ffmpeg's own `-progress` stream, which reports what it
        actually wrote. `ffprobe` is not usable here: from a non-seekable pipe
        it reports no duration at all for either container, and probing a file
        instead would need the temp file this pipeline has nowhere to put.
        """
        clip = await compressor.compress(
            tone(seconds=0.75), pcm_format=PCM, target_format="ogg-opus"
        )

        assert clip.duration_ms is not None
        assert 700 <= clip.duration_ms <= 800

    async def test_the_input_format_comes_from_the_provider_declaration(self):
        """A rate the encoder is *told* is wrong yields a clip of the wrong
        length — the audible failure `pcm_format()` exists to prevent (§8.1).

        Worth pinning because nothing else can catch it: the bytes transcode
        cleanly and the artifact is structurally perfect at either rate.
        """
        pcm = tone(seconds=1.0)
        halved = PcmFormat(sample_rate_hz=12000, channels=1, bits_per_sample=16)

        clip = await FfmpegCompressor(concurrency=1).compress(
            pcm, pcm_format=halved, target_format="ogg-opus"
        )

        assert clip.duration_ms is not None
        assert clip.duration_ms > 1800  # ~2 s of audio from 1 s of samples


class TestNoTempFiles:
    async def test_encoding_writes_nothing_to_disk(
        self, compressor, tmp_path, monkeypatch
    ):
        """§10.1: stdin to stdout, no staging directory.

        Not a style preference — the production root filesystem is read-only,
        so a design that reached for a temp file would pass every test on a
        developer's laptop and fail on the first real clip.
        """
        before = set(os.listdir(tempfile.gettempdir()))
        monkeypatch.chdir(tmp_path)

        await compressor.compress(tone(), pcm_format=PCM, target_format="ogg-opus")

        assert set(os.listdir(tempfile.gettempdir())) == before
        assert list(tmp_path.iterdir()) == []


# A rate ffmpeg itself rejects ("Invalid sample rate"), so these exercise the
# real encoder's failure path rather than this module's own argument guard —
# which is a different test, below.
UNENCODABLE = PcmFormat(sample_rate_hz=0, channels=1, bits_per_sample=16)


class TestFailures:
    async def test_a_failing_encoder_raises_with_its_own_diagnostic(self, compressor):
        """The failure must carry ffmpeg's complaint, not just a status code —
        the tail logs this and it is the only clue a deployment will get."""
        with pytest.raises(CompressionError) as excinfo:
            await compressor.compress(
                tone(), pcm_format=UNENCODABLE, target_format="ogg-opus"
            )

        message = str(excinfo.value)
        assert "ffmpeg exited" in message
        # The encoder's own words, whatever they are — asserting a specific
        # phrase would pin an ffmpeg version's wording rather than the contract,
        # which is that the diagnostic survives to the log.
        assert "no diagnostic output" not in message
        assert "invalid" in message.lower()

    async def test_progress_chatter_is_stripped_from_the_error_text(self, compressor):
        """`-progress pipe:2` shares stderr with real diagnostics, so an error
        must not arrive buried in `key=value` telemetry."""
        with pytest.raises(CompressionError) as excinfo:
            await compressor.compress(
                tone(), pcm_format=UNENCODABLE, target_format="ogg-opus"
            )

        assert "out_time_us" not in str(excinfo.value)
        assert "progress=" not in str(excinfo.value)

    async def test_an_unknown_target_format_never_reaches_the_encoder(self, compressor):
        """Caught in this module, before a subprocess exists — the formats are
        a closed set (§7.1) and an unknown one is a programming error, not a
        transcoding one."""
        with pytest.raises(CompressionError, match="Unsupported format"):
            await compressor.compress(
                tone(), pcm_format=PCM, target_format="not-a-format"
            )

    async def test_a_missing_binary_fails_the_tail_and_nothing_else(self):
        """A deployment with no encoder must fail per-clip, not at import —
        which is why `resolve_ffmpeg_binary` returns a name it cannot find
        rather than raising on the way up."""
        compressor = FfmpegCompressor(concurrency=1, binary="/nonexistent/ffmpeg")

        with pytest.raises(FileNotFoundError):
            await compressor.compress(tone(), pcm_format=PCM, target_format="ogg-opus")

    def test_something_absolute_resolves_on_this_machine(self):
        """Whatever this developer has, it is a real path and not a bare name.

        ⚠ This used to claim it proved §10.2's packaging — "if this resolves to
        a bare `ffmpeg` from PATH, the wheel stopped shipping a binary". It
        never could: **the assertion passes on a machine with ffmpeg installed
        even when the wheel ships nothing**, which is exactly what happens on
        musl. Phase 09 found that in the container, not here, and the honest
        scope of this test is now in its name.
        """
        assert os.path.isabs(resolve_ffmpeg_binary())

    def test_a_bundled_binary_that_raises_falls_through_to_path(self, monkeypatch):
        """The musl regression (2026-08-16), and the reason it was expensive.

        On `python:3.14-alpine` there is no `imageio-ffmpeg` wheel, so uv
        installs the sdist and `get_ffmpeg_exe()` raises **RuntimeError**. The
        resolver caught only `ImportError`, so the exception escaped through
        `FfmpegCompressor.__init__` and `TtsService.__init__` — and `POST
        /tts/generate`, which never encodes anything, answered **500** in the
        container while every test here passed on a glibc host.

        The bar this pins: an unusable *optional* encoder degrades the tail,
        never the service.
        """
        import imageio_ffmpeg

        def raise_like_musl() -> str:
            raise RuntimeError("No ffmpeg exe could be found.")

        monkeypatch.setattr(imageio_ffmpeg, "get_ffmpeg_exe", raise_like_musl)

        resolved = resolve_ffmpeg_binary()

        # Either a real ffmpeg from PATH, or the last-resort name that fails at
        # the first encode. Both are fine; raising is not.
        assert resolved == shutil.which("ffmpeg") or resolved == "ffmpeg"
        # And the compressor still builds, which is what the service needs.
        assert FfmpegCompressor(concurrency=1) is not None


class TestConcurrencyBound:
    async def test_the_semaphore_bounds_encodes_in_flight(self):
        """`TTS_FFMPEG_CONCURRENCY` (§10.1). The bound is held across the whole
        subprocess, not just its spawn — bounding starts would leave the thing
        it means to bound (CPU and RSS) unbounded."""
        compressor = FfmpegCompressor(concurrency=1)
        live = 0
        peak = 0
        original = asyncio.create_subprocess_exec

        async def counting(*args, **kwargs):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            process = await original(*args, **kwargs)
            original_communicate = process.communicate

            async def communicate(*a, **k):
                try:
                    return await original_communicate(*a, **k)
                finally:
                    nonlocal live
                    live -= 1

            process.communicate = communicate  # type: ignore[method-assign]
            return process

        asyncio.create_subprocess_exec = counting  # type: ignore[assignment]
        try:
            await asyncio.gather(
                *(
                    compressor.compress(
                        tone(seconds=0.1), pcm_format=PCM, target_format="ogg-opus"
                    )
                    for _ in range(4)
                )
            )
        finally:
            asyncio.create_subprocess_exec = original  # type: ignore[assignment]

        assert peak == 1
