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

    def synthesize_stream(self, request: TtsProviderRequest) -> AsyncIterator[bytes]:
        """Yield raw PCM audio chunks as the provider produces them.

        Streaming rather than returning bytes is load-bearing: the first
        listener is served live from the growing buffer (§7.2.1), so time to
        first audio does not wait on the whole clip.
        """
        ...
