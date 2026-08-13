# src/app/services/tts/provider.py
"""
The provider-neutral synthesis seam (source-tts proposal §8.1).

Everything a provider does NOT do is as important as what it does: buffering,
hashing, transcoding, storage and HTTP all live outside it. A provider turns a
recipe into a stream of PCM bytes and tells the identity layer which protocol
fields it ignores — nothing else.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PcmFormat:
    """The shape of the raw PCM a provider yields.

    Three numbers, and they exist because the streaming WAV header has to be
    written *before* the first audio byte arrives (§7.2.1) — time to first byte
    is the whole point of streaming, so the header cannot wait to learn the
    format from the stream. The provider therefore declares it up front, and is
    responsible for aborting its own stream if what arrives disagrees (§8.2).

    Provider-declared rather than configured on purpose: an env var here would
    let an operator write a header that contradicts the bytes, which is exactly
    the silent corruption the assertion is meant to catch. It is also what the
    compression tail will need (`-f s16le -ar 24000 -ac 1`, §10.1).
    """

    sample_rate_hz: int
    channels: int
    bits_per_sample: int

    @property
    def byte_rate(self) -> int:
        """Bytes of PCM per second — the WAV header field, and the sizing unit."""
        return self.sample_rate_hz * self.channels * self.bits_per_sample // 8


@dataclass(frozen=True)
class TtsProviderRequest:
    """One synthesis request, already resolved against configuration.

    Every field here is a *resolved* value: `voice` and `model` are never None
    (defaults were applied upstream), and `lang_code` is the caller's hint —
    still un-normalized, because whether it matters is the provider's own
    declaration to make.
    """

    text: str
    voice: str
    model: str
    lang_code: str | None = None


@runtime_checkable
class TtsProvider(Protocol):
    """A speech synthesizer.

    `runtime_checkable` so a test fake can be asserted to satisfy the seam
    without inheriting from it; note that this only checks method presence,
    which is all that is wanted here.
    """

    def non_byte_affecting_fields(self) -> frozenset[str]:
        """Protocol fields this provider ignores when producing bytes (§9.1).

        These are blanked out of the recipe before hashing, so requests that
        differ only in an ignored field resolve to one artifact and one billing
        event. A provider for which a field *does* change output simply leaves
        it out of this set and it participates in identity again.

        Names are the wire/recipe field names (e.g. `"lang_code"`).
        """
        ...

    def pcm_format(self) -> PcmFormat:
        """The PCM format `synthesize_stream` produces (§8.2).

        A declaration, like `non_byte_affecting_fields()` above: the provider
        states a property of itself and the layers above use it — here to write
        the streaming WAV header before any audio exists. A provider must abort
        its stream rather than yield bytes that contradict this.
        """
        ...

    def synthesize_stream(self, request: TtsProviderRequest) -> AsyncIterator[bytes]:
        """Yield raw PCM audio chunks as the provider produces them.

        Streaming rather than returning bytes is load-bearing: the first
        listener is served live from the growing buffer (§7.2.1), so time to
        first audio does not wait on the whole clip.

        Raising is the only way to fail. Ending the iteration early would be
        read as a complete (if short) clip and stored as one, which is the
        silent corruption §7.2.1 exists to prevent — so a provider that detects
        trouble mid-stream, including an error arriving *in-band* as an
        ordinary iteration value, must raise rather than return.
        """
        ...
