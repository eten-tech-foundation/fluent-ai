# src/app/services/tts/wav.py
"""
The streaming WAV header (source-tts proposal §7.2.1, T22).

One function, and the whole design of the live-listen era rests on it: audio
starts flowing to the browser before anyone knows how long the clip is, so the
two size fields are written as `0xFFFFFFFF` ("unknown") and are **never
backfilled**. A chunked response has no seekable start to rewrite anyway.

That choice is what makes the abort-never-clean-EOF rule (§7.2.1) mandatory
rather than stylistic: with unknown-length sizes, a stream that simply stops is
byte-for-byte indistinguishable from a legitimately short verse, so a truncated
clip could only be recognised as broken by the connection breaking.
"""

import struct

from app.services.tts.provider import PcmFormat


UNKNOWN_SIZE = 0xFFFFFFFF
"""The RIFF/data size written when the length is not yet knowable.

Every mainstream player treats it as "read until the stream ends", which is
precisely the semantics of a live synthesis.
"""

WAV_HEADER_BYTES = 44
"""Length of the canonical header below.

Named because the compression tail (§10.1) skips exactly these bytes to feed
ffmpeg raw PCM with explicit parameters.
"""

_PCM_FORMAT_TAG = 1
"""WAVE_FORMAT_PCM — uncompressed integer samples, which is what Gemini yields."""


def streaming_wav_header(pcm: PcmFormat) -> bytes:
    """Build the 44-byte canonical WAV header for an unknown-length stream.

    The format numbers come from the provider's own declaration (§8.2), not
    from configuration: a header that disagrees with the bytes behind it is a
    clip that plays at the wrong pitch, which no test of ours would catch and
    every listener would.
    """
    block_align = pcm.channels * pcm.bits_per_sample // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        UNKNOWN_SIZE,
        b"WAVE",
        b"fmt ",
        16,  # PCM fmt chunk length
        _PCM_FORMAT_TAG,
        pcm.channels,
        pcm.sample_rate_hz,
        pcm.byte_rate,
        block_align,
        pcm.bits_per_sample,
        b"data",
        UNKNOWN_SIZE,
    )
