"""
tests/tts/test_gemini_provider.py — the Gemini Interactions loop (§8.1, §8.2).

Built on the SDK's **real** event objects (`google.genai.interactions`), not
stand-ins, and that is the point: the 1.x → 2.x jump moved every one of these
field names, and the failure mode was a live `400` that no amount of reading
would have caught. A test that invented its own event shapes would have kept
passing through exactly that change.

The faked seam is the SDK client itself — one object with the
`aio.interactions.create` surface — so the argument shape, the event branching,
the base64 decode and the format assertion are all this module's own code.
"""

import base64

import pytest
from google.genai import interactions as sdk

from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException, ServiceUnavailableException
from app.services.tts.gemini_provider import GEMINI_PCM, GeminiTtsProvider
from app.services.tts.provider import TtsProviderRequest


PCM = b"\x01\x02" * 960


def audio_event(
    data: bytes = PCM,
    *,
    mime_type: str = "audio/l16",
    sample_rate: int | None = 24000,
    channels: int | None = 1,
) -> sdk.StepDelta:
    return sdk.StepDelta(
        index=0,
        delta=sdk.AudioDelta(
            data=base64.b64encode(data).decode(),
            mime_type=mime_type,
            sample_rate=sample_rate,
            channels=channels,
        ),
    )


def text_event(text: str = "In the beginning") -> sdk.StepDelta:
    """§8.2's documented glitch: a text token inside an audio response."""
    return sdk.StepDelta(index=0, delta=sdk.TextDelta(text=text))


def error_event(message: str = "upstream exploded") -> sdk.ErrorEvent:
    return sdk.ErrorEvent(error=sdk.Error(code="internal", message=message))


class FakeStream:
    """The SDK's `AsyncStream`, reduced to what the provider actually uses."""

    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class FakeInteractions:
    def __init__(self, events):
        self._events = events
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self._events)


class FakeGenaiClient:
    def __init__(self, events):
        self.aio = type("Aio", (), {})()
        self.aio.interactions = FakeInteractions(events)


def provider_for(events) -> tuple[GeminiTtsProvider, FakeGenaiClient]:
    client = FakeGenaiClient(events)
    return GeminiTtsProvider(api_key="k", client=client), client  # type: ignore[arg-type]


REQUEST = TtsProviderRequest(
    text="In the beginning", voice="Kore", model="gemini-3.1-flash-tts-preview"
)


async def collect(provider: GeminiTtsProvider, request=REQUEST) -> bytes:
    return b"".join([chunk async for chunk in provider.synthesize_stream(request)])


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


class TestDeclarations:
    def test_lang_code_is_declared_non_byte_affecting(self):
        assert GeminiTtsProvider().non_byte_affecting_fields() == frozenset(
            {"lang_code"}
        )

    def test_the_declared_format_is_the_documented_one(self):
        """24 kHz mono 16-bit (§8.2), which is also what the streaming WAV
        header is built from — so a change here changes the header, and the
        per-delta assertion below then catches any disagreement."""
        assert GeminiTtsProvider().pcm_format() == GEMINI_PCM
        assert (GEMINI_PCM.sample_rate_hz, GEMINI_PCM.channels) == (24000, 1)
        assert GEMINI_PCM.byte_rate == 48000


# ---------------------------------------------------------------------------
# The 2.x call shape (§8.2's corrections)
# ---------------------------------------------------------------------------


class TestCallShape:
    async def test_the_request_matches_the_2x_interactions_schema(self):
        """All four corrections in one assertion. `speech_config` nests inside
        `generation_config` and is a LIST; `response_format` replaced
        `response_modalities`; streaming is explicit."""
        provider, client = provider_for([audio_event()])

        await collect(provider)

        call = client.aio.interactions.calls[0]
        assert call["model"] == "gemini-3.1-flash-tts-preview"
        assert call["input"] == "In the beginning"
        assert call["stream"] is True
        assert call["response_format"] == {"type": "audio"}
        assert call["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
        assert "response_modalities" not in call  # gone in 2.x
        assert "speech_config" not in call  # never top-level


# ---------------------------------------------------------------------------
# Audio deltas
# ---------------------------------------------------------------------------


class TestAudioDeltas:
    async def test_audio_arrives_base64_and_is_decoded(self):
        """There is no `chunk.audio_bytes` in any SDK version: `data` is a
        base64 *string*, and appending it undecoded would store four bytes of
        ASCII for every three bytes of audio."""
        provider, _ = provider_for([audio_event(b"\x00\x01\x02\x03")])

        assert await collect(provider) == b"\x00\x01\x02\x03"

    async def test_every_delta_is_appended_in_order(self):
        provider, _ = provider_for(
            [audio_event(b"one!"), audio_event(b"two!"), audio_event(b"three!!!")]
        )

        assert await collect(provider) == b"one!two!three!!!"

    async def test_lifecycle_events_are_ignored(self):
        """`interaction.created`, `step.stop` and friends carry no audio; the
        loop must skip them rather than treat them as anything."""
        provider, _ = provider_for(
            [sdk.StepStop(index=0), audio_event(b"audio"), sdk.StepStop(index=1)]
        )

        assert await collect(provider) == b"audio"


# ---------------------------------------------------------------------------
# Failure paths — all of them are "raise", never "stop early"
# ---------------------------------------------------------------------------


class TestFailures:
    async def test_an_in_band_error_event_raises(self):
        """The headline consequence of the 2.x shape: an error arrives as an
        ordinary iteration value. A loop that only caught exceptions would read
        this stream as a successful two-chunk clip and store it forever."""
        provider, _ = provider_for(
            [audio_event(b"partial"), error_event(), audio_event(b"unreachable")]
        )

        with pytest.raises(ExternalServiceException) as excinfo:
            await collect(provider)

        assert excinfo.value.code == ErrorCode.TTS_PROVIDER_UNAVAILABLE
        assert excinfo.value.status_code == 502

    async def test_a_stray_text_token_fails_the_generation(self):
        """§8.2's known glitch, detected by delta *type* rather than guessed at
        — and treated as a failed generation with no special-casing (readers
        abort; the client retries)."""
        provider, _ = provider_for([audio_event(), text_event()])

        with pytest.raises(ExternalServiceException) as excinfo:
            await collect(provider)

        assert "non-audio delta" in excinfo.value.message
        assert excinfo.value.details == {"detail": "delta type 'text'"}

    @pytest.mark.parametrize(
        "delta_kwargs",
        [
            {"mime_type": "audio/wav"},  # would smuggle a second header inline
            {"sample_rate": 16000},  # would play at the wrong pitch
            {"channels": 2},
        ],
    )
    async def test_a_format_change_under_us_aborts(self, delta_kwargs):
        """The WAV header goes out before the first audio byte (§7.2.1), so a
        format change cannot be accommodated — only detected. This assertion is
        the tripwire that keeps a wrong-pitch clip from becoming the stored
        artifact."""
        provider, _ = provider_for([audio_event(**delta_kwargs)])

        with pytest.raises(ExternalServiceException) as excinfo:
            await collect(provider)

        assert "does not match the streamed WAV header" in excinfo.value.message

    async def test_a_stream_with_no_audio_at_all_raises(self):
        """An empty result must never look like a successful silent clip — it
        would be stored as one."""
        provider, _ = provider_for([sdk.StepStop(index=0)])

        with pytest.raises(ExternalServiceException) as excinfo:
            await collect(provider)

        assert "no audio" in excinfo.value.message

    async def test_undecodable_audio_raises(self):
        broken = sdk.StepDelta(
            index=0,
            delta=sdk.AudioDelta(data="not base64!!", mime_type="audio/l16"),
        )
        provider, _ = provider_for([broken])

        with pytest.raises(ExternalServiceException):
            await collect(provider)

    async def test_a_missing_api_key_fails_the_generation_not_the_boot(self):
        """A deployment with no Google key still boots and still authorizes
        recipes; only synthesis fails, and it says why."""
        provider = GeminiTtsProvider(api_key=None)

        with pytest.raises(ServiceUnavailableException) as excinfo:
            await collect(provider)

        assert excinfo.value.code == ErrorCode.TTS_PROVIDER_UNAVAILABLE

    async def test_the_spoken_text_never_appears_in_a_failure(self):
        """Failures travel into logs and error details; the recipe's text is
        the content itself and must not ride along."""
        provider, _ = provider_for([text_event("Genesis 1:1 as spoken")])

        with pytest.raises(ExternalServiceException) as excinfo:
            await collect(
                provider,
                TtsProviderRequest(text="a secret verse", voice="Kore", model="m"),
            )

        rendered = f"{excinfo.value.message} {excinfo.value.details}"
        assert "secret verse" not in rendered
        assert "Genesis 1:1 as spoken" not in rendered
