"""The compression step of the generation tail (source-tts proposal §10.1).

**This module is the whole ffmpeg seam, on purpose.** B5 — whether ffmpeg
arrives as a pip-bundled binary or as the team's shared `transcode-mcp`
container — is still open, and the answer changes *how* a clip is encoded but
nothing about when or by whom. So the tail depends on `Compressor` (two
methods, no subprocess vocabulary in the signatures) and swapping in a network
transcoder is a new class in this file, not a change to `TtsService`.

Two constraints from §10.1 shape everything here:

* **No temp files, ever.** Production runs on a read-only root filesystem, and
  the design has no staging directory by construction — the clip exists in the
  heap buffer and then on R2. So PCM goes in on stdin and the container comes
  back on stdout.
* **Only pipe-safe containers.** Ogg and MP3 can be written to a non-seekable
  output; MP4-family containers cannot, because they seek back to write the
  `moov` atom once the stream length is known. That is a hard constraint on
  this pipeline, and it is one of the reasons `ogg-opus` and `mp3` are the only
  requestable formats (§7.1). **Adding an m4a/aac format would break here, not
  at the API edge** — do not add one without replacing this transport.
"""

import asyncio
import shutil
from dataclasses import dataclass
from typing import Protocol

from app.logging.utils import get_logger
from app.services.tts.provider import PcmFormat


logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Encoder settings
# --------------------------------------------------------------------------- #

OPUS_BITRATE = "32k"
"""Opus target for 24 kHz mono speech.

**Chosen from codec convention, not measured on our own audio** — flagged
because this project has been bitten by numbers that looked derived and were
not. Opus was designed for exactly this signal (mono voice, low rate) and is
transparent for speech well below 32 kbps; the same figure is what voice chat
ships. A 1.5 s tone encodes to 9.4x smaller than its PCM here, consistent with
§7.2.1's "~10x fewer bytes" claim for the compressed era.

**What would settle it:** phase 09's smoke test produces real verses. Listen to
one before assuming this is right, and remember that changing it later is free
for *new* artifacts and impossible for old ones — §9.4 has no eviction, so
every clip already in R2 keeps the bitrate it was encoded at.
"""

MP3_BITRATE = "64k"
"""MP3 target, roughly quality-matched to `OPUS_BITRATE`.

Twice the bits for the same speech because MP3 is markedly less efficient at
low rates. This is the fallback format — sent only when a browser reports no
Opus support (§6.1) — so it is the rarer artifact and the looser choice.
"""

_PROGRESS_DURATION_KEY = "out_time_us"


@dataclass(frozen=True, slots=True)
class CompressedClip:
    """What the tail uploads, plus the metadata the receipt wants."""

    data: bytes
    duration_ms: int | None
    content_type: str


class CompressionError(RuntimeError):
    """The encoder failed. Raised with the encoder's own stderr, trimmed."""


class Compressor(Protocol):
    """The seam B5's answer swaps out (see the module docstring)."""

    async def compress(
        self, pcm: bytes, *, pcm_format: PcmFormat, target_format: str
    ) -> CompressedClip: ...


def resolve_ffmpeg_binary() -> str:
    """Find an ffmpeg to run, preferring the one we ship.

    §10.2's suggested packaging, and the reason it is suggested: `imageio-ffmpeg`
    delivers a static binary as an ordinary wheel, so the encoder arrives with
    `uv sync` and **nothing has to be assumed about what the container
    provisions**. No `apt-get` in the image, no base-image coupling, no
    "works on my machine" gap between dev and deploy.

    Falling back to `PATH` rather than failing keeps two things working: a
    developer whose environment already has ffmpeg, and any future deployment
    that would rather supply its own build (see the license note below). If
    neither exists the failure is deliberately deferred to the first encode,
    not raised at import — a deployment that never speaks a verse must still
    boot, which is the same rule the rest of the TTS config follows.

    ⚠ **The bundled binary is built `--enable-gpl --enable-version3` and is
    ~77 MB.** Invoking it as a subprocess (rather than linking it) is the
    ordinary way to use ffmpeg without the GPL reaching our own source, but the
    container does then distribute GPL software, and the image grows. Both are
    inputs to B5, which is a team decision and not settled here.
    """
    try:
        import imageio_ffmpeg
    except ImportError:  # pragma: no cover - the dependency is declared
        bundled = None
    else:
        bundled = imageio_ffmpeg.get_ffmpeg_exe()

    if bundled:
        return bundled

    found = shutil.which("ffmpeg")
    if found:  # pragma: no cover - environment-dependent
        logger.info("tts using ffmpeg from PATH", binary=found)
        return found

    # Deferred, not raised: see the docstring. `compress` will fail with the
    # OS's own "no such file" through the normal honest-failure path.
    logger.warning("tts found no ffmpeg binary; compression will fail")
    return "ffmpeg"


class FfmpegCompressor:
    """Encodes via a local `ffmpeg` subprocess, stdin to stdout.

    The semaphore is held across the whole subprocess rather than just its
    spawn: bounding *starts* would let unbounded encodes run concurrently,
    which is the resource this is meant to bound (§10.1 — worst-case CPU and
    RSS stay flat while the RAM budget accounts for buffers separately).
    """

    def __init__(self, *, concurrency: int, binary: str | None = None) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._binary = binary or resolve_ffmpeg_binary()

    async def compress(
        self, pcm: bytes, *, pcm_format: PcmFormat, target_format: str
    ) -> CompressedClip:
        """Transcode raw PCM into `target_format`, in memory, both ways."""
        argv = self._argv(pcm_format, target_format)
        async with self._semaphore:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # `communicate` and not a hand-rolled write-then-read: ffmpeg emits
            # container bytes while it is still consuming stdin, so writing the
            # whole input before reading any output deadlocks on the pipe
            # buffer for any clip bigger than it (64 KiB — i.e. every real
            # verse). `communicate` pumps both directions concurrently.
            stdout, stderr = await process.communicate(pcm)

        if process.returncode != 0:
            raise CompressionError(
                f"ffmpeg exited {process.returncode}: {_error_text(stderr)}"
            )
        if not stdout:
            # A zero-exit encoder that produced nothing would otherwise be
            # stored as a valid empty artifact — permanently, under §9.4's
            # no-eviction rule. Same reasoning as the provider's empty-stream
            # check (§8.2): refuse to store silence.
            raise CompressionError("ffmpeg produced no output bytes")

        return CompressedClip(
            data=stdout,
            duration_ms=_duration_ms(stderr),
            content_type=_CONTENT_TYPES[target_format],
        )

    def _argv(self, pcm_format: PcmFormat, target_format: str) -> list[str]:
        """Build the command line, input flags from the provider's declaration.

        The three input numbers come from `pcm_format()` and never from
        configuration — the same single source that writes the streaming WAV
        header (§8.1). If they disagreed with the samples, this transcode would
        succeed and produce a clip at the wrong speed and pitch.
        """
        try:
            encoder = _ENCODERS[target_format]
        except KeyError:  # pragma: no cover - unreachable via the API's Literal
            raise CompressionError(f"Unsupported format: {target_format}") from None

        return [
            self._binary,
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-loglevel",
            "error",
            # Machine-readable progress on stderr, which is how the receipt's
            # duration is obtained without a second process. `ffprobe` cannot
            # help here: from a non-seekable pipe it reports no duration at all
            # for either container (verified), and the alternative — writing
            # the output to a file to probe it — is exactly the temp file this
            # design does not have anywhere to put.
            "-progress",
            "pipe:2",
            "-f",
            _SAMPLE_FORMATS[pcm_format.bits_per_sample],
            "-ar",
            str(pcm_format.sample_rate_hz),
            "-ac",
            str(pcm_format.channels),
            "-i",
            "pipe:0",
            *encoder,
            "pipe:1",
        ]


_ENCODERS: dict[str, tuple[str, ...]] = {
    "ogg-opus": ("-c:a", "libopus", "-b:a", OPUS_BITRATE, "-f", "ogg"),
    "mp3": ("-c:a", "libmp3lame", "-b:a", MP3_BITRATE, "-f", "mp3"),
}

_CONTENT_TYPES: dict[str, str] = {"ogg-opus": "audio/ogg", "mp3": "audio/mpeg"}

_SAMPLE_FORMATS: dict[int, str] = {16: "s16le"}
"""PCM bit depth to ffmpeg's input format name.

A dict rather than an f-string so an unexpected depth raises here instead of
handing ffmpeg a format name it will reject with a less legible message. Only
16-bit exists today — it is what Gemini's `audio/l16` yields.
"""


def _duration_ms(stderr: bytes) -> int | None:
    """Read `out_time_us` from ffmpeg's `-progress` stream.

    Best-effort by contract: this feeds the receipt, which nothing may require
    (§9.3), so an unparseable progress stream costs a null field and never a
    failed artifact. The last value wins — `-progress` reports periodically and
    the final block is the one written at `progress=end`.
    """
    duration_us: int | None = None
    for line in stderr.decode("utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == _PROGRESS_DURATION_KEY:
            try:
                duration_us = int(value.strip())
            except ValueError:
                continue
    return None if duration_us is None else duration_us // 1000


def _error_text(stderr: bytes, *, limit: int = 500) -> str:
    """The encoder's complaint, with the progress chatter stripped out.

    `-progress pipe:2` shares stderr with real diagnostics, so a failure's
    output is progress lines plus the actual error. Dropping `key=value` lines
    leaves the part worth logging.
    """
    lines = [
        line.strip()
        for line in stderr.decode("utf-8", errors="replace").splitlines()
        if line.strip() and "=" not in line
    ]
    return " ".join(lines)[:limit] or "no diagnostic output"
