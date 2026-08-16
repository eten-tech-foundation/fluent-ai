"""
tests/api/v1/test_tts_audio.py — GET|HEAD /tts/audio/{hash}.wav (§7.2, §7.2.1).

Driven over ASGI with an async client rather than `TestClient`, because the
things worth proving here are concurrent: two listeners attaching to one
generation, and an admission refusal that must arrive while another clip holds
the budget. Only botocore and the provider are fakes — the waterfall, the
admission gate, the streaming reader and the HTTP layer all run for real.
"""

import asyncio
import gc
import struct

import httpx
import pytest

from app.dependencies import get_tts_service, require_api_key
from app.errors.codes import ErrorCode
from app.main import app
from app.schemas.tts import TtsGenerateRequest
from app.services.tts.artifacts import TtsArtifactStore, serialize_json_body
from app.services.tts.recipe import artifact_hash, build_recipe
from app.services.tts.service import TtsService
from app.services.tts.wav import UNKNOWN_SIZE, WAV_HEADER_BYTES
from tests.tts.fakes import (
    FakeCompressor,
    FakeS3Client,
    FakeTtsProvider,
    tts_settings,
)


PCM_CHUNK = b"\x01\x02" * 960  # 1920 bytes = one 40 ms Gemini delta (§8.2)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def r2() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def provider() -> FakeTtsProvider:
    return FakeTtsProvider(chunks=[PCM_CHUNK, PCM_CHUNK, PCM_CHUNK])


@pytest.fixture
def settings():
    return tts_settings(tts_admission_wait_seconds=0.05)


@pytest.fixture
def compressor() -> FakeCompressor:
    return FakeCompressor()


@pytest.fixture
def service(r2, provider, settings, compressor) -> TtsService:
    store = TtsArtifactStore(
        client=r2,  # type: ignore[arg-type] - fake with the same call surface
        bucket=settings.r2_tts_bucket or "bucket",
        prefix=settings.tts_r2_prefix,
    )
    return TtsService(
        settings=settings,
        store=store,
        provider=provider,
        compressor=compressor,
    )


@pytest.fixture
async def audio_client(service):
    """An authenticated ASGI client with the TTS service swapped for a fake."""
    app.dependency_overrides[require_api_key] = lambda: object()
    app.dependency_overrides[get_tts_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ai") as client:
        yield client
    app.dependency_overrides.pop(require_api_key, None)
    app.dependency_overrides.pop(get_tts_service, None)


def authorize(r2, settings, provider, text: str = "In the beginning") -> str:
    """Write the request sidecar `generate` would have written, and return the
    hash — i.e. put the artifact on rung 3 of the waterfall."""
    recipe = build_recipe(
        TtsGenerateRequest(text=text), settings=settings, provider=provider
    )
    digest = artifact_hash(recipe, secret=settings.tts_hash_secret)
    r2.objects[f"{settings.tts_r2_prefix}requests/{digest}.json"] = {
        "body": serialize_json_body(recipe.to_sidecar_dict()),
        "content_type": "application/json",
    }
    return digest


def url(digest: str) -> str:
    return f"/tts/audio/{digest}.wav"


async def settle_tail(service: TtsService, digest: str) -> None:
    """Wait for a finished clip's compression tail to run to completion.

    A response ending is not the generation ending. The reader has every byte
    once `state` flips to `complete`, but the detached task then runs the tail
    (§10.1) — and the entry stays in the *primary* dict until its object is
    uploaded (§9.2), which is exactly the window in which a new request still
    attaches to the live entry instead of being redirected. A test that reads
    the compressed era straight after a streaming one is therefore racing the
    upload unless it waits here.

    Awaiting the task rather than sleeping: no timing guess, and `entry.task`
    being `None` already means the tail is done, because the done-callback that
    clears it runs after the tail (§8.3).
    """
    entry = service.heap.get(digest)
    if entry is not None and entry.task is not None:
        await asyncio.wait([entry.task])


# ---------------------------------------------------------------------------
# Rung 3 — sidecar present ⇒ generate and stream (§7.2)
# ---------------------------------------------------------------------------


class TestStreamingEra:
    async def test_a_first_listen_streams_a_wav_built_from_the_buffer(
        self, audio_client, r2, settings, provider
    ):
        digest = authorize(r2, settings, provider)

        response = await audio_client.get(url(digest))

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content == b"".join(
            [response.content[:WAV_HEADER_BYTES], PCM_CHUNK * 3]
        )
        assert len(provider.synthesize_calls) == 1

    async def test_the_ff_size_header_is_never_rewritten(
        self, audio_client, r2, settings, provider
    ):
        """T22: the sizes stay `0xFFFFFFFF` even though, by the time the last
        byte is sent, the true length is known. Backfilling would need a seek
        the wire does not have — and the unknown length is what makes an
        aborted connection the only honest failure signal."""
        digest = authorize(r2, settings, provider)

        body = (await audio_client.get(url(digest))).content

        assert body[:4] == b"RIFF"
        assert struct.unpack("<I", body[4:8])[0] == UNKNOWN_SIZE
        assert struct.unpack("<I", body[40:44])[0] == UNKNOWN_SIZE
        assert len(body) == WAV_HEADER_BYTES + 3 * len(PCM_CHUNK)

    async def test_streaming_headers_say_no_length_no_range_private_cache(
        self, audio_client, r2, settings, provider
    ):
        """§7.2: chunked with no Content-Length, no Range, and `private` so
        shared caches stay out of a URL whose representation changes when
        compression finishes."""
        digest = authorize(r2, settings, provider)

        async with audio_client.stream("GET", url(digest)) as response:
            assert "content-length" not in response.headers
            assert response.headers["accept-ranges"] == "none"
            assert response.headers["cache-control"].startswith("private")
            await response.aread()

    async def test_concurrent_listeners_share_one_generation(
        self, audio_client, r2, settings, provider
    ):
        """§12.3's dedup case: two requests for one hash, **ONE provider call**.
        This is what makes a double-clicked play button (or a re-run React
        effect) cost one billing event instead of two.

        The second request may land in either era, and the test deliberately
        accepts both — it is asserting dedup, not timing. What makes dedup hold
        *at every instant* rather than usually is a handover with no gap in it:
        an entry stays in the primary dict until its compressed object is
        uploaded (§9.2, and `_finish_generation` drains only after the tail),
        so the second request either finds the live entry and attaches, or
        finds the object and is redirected. There is no moment where both are
        missing and it would regenerate.

        (The reverse is visible when the tail *fails*: the entry drains with no
        object, and a late second request correctly regenerates. That path is
        covered at the service layer in `test_waterfall.py`, which is also
        where genuinely-concurrent attachment is tested — httpx's ASGI
        transport buffers a whole response, so these two requests cannot
        actually overlap here.)
        """
        digest = authorize(r2, settings, provider)
        provider.paced = True
        provider.release(3)

        first, second = await asyncio.gather(
            audio_client.get(url(digest)), audio_client.get(url(digest))
        )

        assert first.status_code == 200
        assert second.status_code in (200, 302)
        assert len(provider.synthesize_calls) == 1


# ---------------------------------------------------------------------------
# Rung 2 — the compressed object exists (§7.2, T22)
# ---------------------------------------------------------------------------


class TestCompressedEra:
    async def test_it_is_a_302_to_the_immutable_public_object(
        self, audio_client, r2, settings, provider
    ):
        """302, never 301: the `.wav` URL means "whatever representation era
        this artifact is in right now", and a cached permanent redirect would
        freeze that forever."""
        digest = authorize(r2, settings, provider)
        r2.objects[f"{settings.tts_r2_prefix}audio/{digest}.ogg"] = {
            "body": b"compressed",
            "content_type": "audio/ogg",
        }

        response = await audio_client.get(url(digest), follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == (
            f"https://tts.example.test/tts/audio/{digest}.ogg"
        )
        # The extension SWAPPED: one hash resolves to exactly one object,
        # because `format` is inside the hash.
        assert response.headers["location"].endswith(".ogg")
        assert provider.synthesize_calls == []

    async def test_an_mp3_artifact_redirects_to_its_own_extension(
        self, audio_client, r2, settings, provider
    ):
        recipe = build_recipe(
            TtsGenerateRequest(text="Let there be light", format="mp3"),
            settings=settings,
            provider=provider,
        )
        digest = artifact_hash(recipe, secret=settings.tts_hash_secret)
        r2.objects[f"{settings.tts_r2_prefix}requests/{digest}.json"] = {
            "body": serialize_json_body(recipe.to_sidecar_dict()),
            "content_type": "application/json",
        }
        r2.objects[f"{settings.tts_r2_prefix}audio/{digest}.mp3"] = {
            "body": b"compressed",
            "content_type": "audio/mpeg",
        }

        response = await audio_client.get(url(digest), follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"].endswith(f"{digest}.mp3")


# ---------------------------------------------------------------------------
# Rung 4 — nothing was ever authorized (§7.2)
# ---------------------------------------------------------------------------


class TestNotFound:
    async def test_an_unauthorized_hash_is_a_404_and_spends_nothing(
        self, audio_client, provider
    ):
        """A GET can only spend provider money on hashes an authenticated
        `generate` authorized, which is the property that makes this route safe
        to expose behind a session cookie."""
        response = await audio_client.get(url("0" * 64))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.TTS_ARTIFACT_NOT_FOUND
        assert provider.synthesize_calls == []

    async def test_a_name_that_is_not_an_artifact_is_also_a_404(self, audio_client):
        """404 rather than 422 on purpose: fluent-web's failure classifier
        speaks 404/503/302/200, and a fifth status would be an unhandled case
        in the client's recovery ladder."""
        for bad in ("nope.wav", "abc.wav", f"{'a' * 64}.flac", f"{'A' * 64}.wav"):
            response = await audio_client.get(f"/tts/audio/{bad}")
            assert response.status_code == 404, bad

    async def test_every_extension_fluent_api_relays_resolves_here(
        self, audio_client, service, r2, settings, provider
    ):
        """fluent-api's path validator accepts `.wav`, `.ogg` and `.mp3` and
        relays whichever arrived. Serving only `.wav` here would turn its
        defensive breadth into a 404 that neither side's tests cover — and the
        extension was never a lookup key anyway, because `format` is inside the
        hash (§7.2)."""
        digest = authorize(r2, settings, provider)

        streaming = await audio_client.get(f"/tts/audio/{digest}.ogg")
        assert streaming.status_code == 200
        assert streaming.headers["content-type"] == "audio/wav"

        # The compressed era arrives on its own now — the tail uploads it. It
        # used to be planted by hand here, which since phase 08 would race the
        # real upload for the same key.
        await settle_tail(service, digest)
        compressed = await audio_client.get(
            f"/tts/audio/{digest}.mp3", follow_redirects=False
        )
        # Resolved by hash, so the answer is the artifact's own object — the
        # `.mp3` in the request is not a format request and cannot become one.
        assert compressed.status_code == 302
        assert compressed.headers["location"].endswith(f"{digest}.ogg")


# ---------------------------------------------------------------------------
# Admission (§9.2, T25) — the 503 that owes a header
# ---------------------------------------------------------------------------


class TestAdmission:
    async def test_a_saturated_budget_answers_503_with_retry_after_and_no_audio(
        self, audio_client, r2, settings, provider, service
    ):
        """§12.3: brief wait, then `503` + `Retry-After` **before any body
        bytes**. The body is the JSON error envelope — not a truncated WAV a
        media element would try to play."""
        digest = authorize(r2, settings, provider)
        # Saturate the budget with unrelated in-flight generations.
        held = [
            (
                await service.heap.admit(
                    f"{'f' * 63}{index}", TtsGenerateRequest(text="x")
                )
            ).entry
            for index in range(service.heap.slots)
        ]

        response = await audio_client.get(url(digest))

        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"]["code"] == ErrorCode.TTS_BUSY
        assert provider.synthesize_calls == []
        assert len(held) == service.heap.slots

    async def test_attaching_to_an_existing_generation_bypasses_admission(
        self, audio_client, r2, settings, provider, service
    ):
        """The cap gates NEW generations only (§9.2): a listener joining a clip
        that is already being synthesized allocates nothing, so refusing it
        would cost a listen for no memory saved.

        Staged by saturating the budget *around* an in-flight entry, because
        httpx's ASGI transport buffers a whole response — a held-open stream
        cannot be observed from this side of the wire (the reader-level version
        of this case lives in `tests/tts/test_waterfall.py`).
        """
        digest = authorize(r2, settings, provider)
        provider.paced = True
        entry, _ = await service.heap.admit(digest, TtsGenerateRequest(text="x"))
        held = [
            (
                await service.heap.admit(f"{'f' * 63}{i}", TtsGenerateRequest(text="x"))
            ).entry
            for i in range(service.heap.slots - 1)
        ]

        # No slot is free, and yet this attaches: rung 1 never asks for one.
        probe = await audio_client.request("HEAD", url(digest))

        assert probe.status_code == 200
        assert provider.synthesize_calls == []  # attached, did not spawn
        assert len(held) == service.heap.slots - 1
        assert entry.state == "generating"


# ---------------------------------------------------------------------------
# HEAD — fluent-web's failure classifier (§6.1)
# ---------------------------------------------------------------------------


class TestHeadProbe:
    async def test_head_answers_the_waterfall_without_a_body(
        self, audio_client, r2, settings, provider
    ):
        """A streaming body here would attach a reader for the clip's whole
        duration to a request that discards every byte."""
        digest = authorize(r2, settings, provider)

        response = await audio_client.request("HEAD", url(digest))

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content == b""

    async def test_head_classifies_302_and_404_the_same_way_get_does(
        self, audio_client, r2, settings, provider
    ):
        missing = await audio_client.request("HEAD", url("0" * 64))
        assert missing.status_code == 404

        digest = authorize(r2, settings, provider)
        r2.objects[f"{settings.tts_r2_prefix}audio/{digest}.ogg"] = {
            "body": b"compressed",
            "content_type": "audio/ogg",
        }
        compressed = await audio_client.request(
            "HEAD", url(digest), follow_redirects=False
        )
        assert compressed.status_code == 302
        assert compressed.headers["location"].endswith(".ogg")


# ---------------------------------------------------------------------------
# Provider failure (§7.2.1, §8.3, T22)
# ---------------------------------------------------------------------------


class TestProviderFailure:
    async def test_a_mid_stream_failure_aborts_the_connection(
        self, audio_client, r2, settings, provider
    ):
        """The transfer must end incomplete/errored, never cleanly. A polite
        EOF would hand the browser a truncated verse it cannot tell from a
        short one — and, because caches store only complete responses, the
        abort also excludes the partial clip from every cache layer."""
        digest = authorize(r2, settings, provider)
        provider.fail_after = 1

        with pytest.raises(Exception) as excinfo:
            async with audio_client.stream("GET", url(digest)) as response:
                assert response.status_code == 200
                await response.aread()

        assert "failed" in str(excinfo.value).lower()

    async def test_a_failed_generation_is_dropped_and_never_retried_server_side(
        self, audio_client, r2, settings, provider, service
    ):
        """§8.3: no server-side retry. The entry is dropped so the client's own
        retry re-enters through admission, which is what keeps the RAM budget
        in charge of pacing during provider trouble."""
        digest = authorize(r2, settings, provider)
        provider.fail_after = 0

        with pytest.raises(Exception) as excinfo:
            await audio_client.get(url(digest))

        await asyncio.sleep(0)
        assert service.heap.get(digest) is None
        assert len(provider.synthesize_calls) == 1

        # Worth knowing, and true in production too: the abort's traceback
        # holds the reader frame, which holds the entry — so a failed clip's
        # buffer lives exactly as long as its traceback does. Here that is this
        # test's own `excinfo`; under uvicorn it is one error log record. Drop
        # it and the slot comes straight back, so the next listener is not
        # punished for the provider's failure.
        excinfo.value.__traceback__ = None
        del excinfo
        gc.collect()
        await asyncio.sleep(0)
        assert service.heap.buffered_bytes == 0
