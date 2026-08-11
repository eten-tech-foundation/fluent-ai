# src/app/services/tts/gemini_provider.py
"""
Gemini implementation of the TTS provider seam (§8.1, §8.2).

Scope note: only the *identity* half of the seam is implemented here — the
declaration of which protocol fields cannot affect Gemini's output bytes,
which the recipe hash needs (§9.1). Live synthesis belongs to the serving
waterfall (§7.2) and lands with it; until then `synthesize_stream` raises, so
a premature caller fails loudly instead of silently producing no audio.
"""

from collections.abc import AsyncIterator

from app.services.tts.provider import TtsProviderRequest


class GeminiTtsProvider:
    """Speech synthesis via Google's Gemini TTS models.

    Satisfies the `TtsProvider` protocol structurally (no inheritance), so the
    protocol stays a description of the seam rather than a base class that
    invites shared implementation.
    """

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

    def synthesize_stream(self, request: TtsProviderRequest) -> AsyncIterator[bytes]:
        """Not implemented yet — synthesis arrives with the serving waterfall.

        Deliberately a raise rather than an empty stream: an empty async
        iterator would look like a successful zero-byte clip and would be
        stored as one, which is exactly the failure mode §7.2.1's
        abort-never-clean-EOF rule exists to prevent.
        """
        raise NotImplementedError(
            "Gemini streaming synthesis is implemented with the get-audio "
            "waterfall (source-tts proposal §7.2); generate never synthesizes."
        )
