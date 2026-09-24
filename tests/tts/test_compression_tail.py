"""
tests/tts/test_compression_tail.py — what happens after a clip finishes (§10.1).

The tail is the step that makes an artifact *durable*: HEAD, encode, conditional
PUT, receipt, drain. Everything here uses `FakeCompressor` — the encoder itself
is exercised against a real ffmpeg in `test_compression.py`, and mixing the two
would make these assertions about subprocess timing instead of about order and
failure handling.

The governing rule, and the reason several of these tests look lenient: **the
tail can never fail the clip.** Every listener already heard the whole verse
from the buffer before it ran, so a failure here costs durability (the next
`get-audio` regenerates from the sidecar, §7.2 rung 4) and nothing else.
"""

import asyncio

import pytest

from app.schemas.tts import TtsGenerateRequest
from app.services.tts.artifacts import TtsArtifactStore, serialize_json_body
from app.services.tts.recipe import artifact_hash, build_recipe
from app.services.tts.service import AudioStream, TtsService
from tests.tts.fakes import (
    FakeCompressor,
    FakeS3Client,
    FakeTtsProvider,
    tts_settings,
)


PCM_CHUNK = b"\x01\x02" * 960


@pytest.fixture
def r2() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def provider() -> FakeTtsProvider:
    return FakeTtsProvider(chunks=[PCM_CHUNK, PCM_CHUNK])


@pytest.fixture
def settings():
    return tts_settings(tts_admission_wait_seconds=0.05)


@pytest.fixture
def compressor() -> FakeCompressor:
    return FakeCompressor()


@pytest.fixture
def service(r2, provider, settings, compressor) -> TtsService:
    return TtsService(
        settings=settings,
        store=TtsArtifactStore(
            client=r2,
            bucket=settings.r2_tts_bucket or "bucket",
            prefix=settings.tts_r2_prefix,
        ),
        provider=provider,
        compressor=compressor,
    )


def authorize(r2, settings, provider, text: str = "In the beginning") -> str:
    recipe = build_recipe(
        TtsGenerateRequest(text=text), settings=settings, provider=provider
    )
    digest = artifact_hash(recipe, secret=settings.tts_hash_secret)
    r2.objects[f"{settings.tts_r2_prefix}requests/{digest}.json"] = {
        "body": serialize_json_body(recipe.to_sidecar_dict()),
        "content_type": "application/json",
    }
    return digest


async def listen(service: TtsService, digest: str) -> None:
    """Play a clip to the end and let its tail run to completion.

    Awaiting the task rather than sleeping: the reader finishing and the
    generation finishing are different events, and the tail lives between them.
    """
    resolution = await service.resolve_audio(digest)
    assert isinstance(resolution, AudioStream)
    task = resolution.entry.task
    async for _ in resolution.reader():
        pass
    if task is not None:
        await asyncio.wait([task])


def audio_key(settings, digest: str, extension: str = "ogg") -> str:
    return f"{settings.tts_r2_prefix}audio/{digest}.{extension}"


def receipt_key(settings, digest: str) -> str:
    return f"{settings.tts_r2_prefix}receipts/{digest}.json"


class TestTheHappyPath:
    async def test_a_finished_clip_is_encoded_and_uploaded(
        self, service, r2, settings, provider, compressor
    ):
        """The whole point of phase 08: after this, a second listen is a 302
        instead of a second bill."""
        digest = authorize(r2, settings, provider)

        await listen(service, digest)

        stored = r2.objects[audio_key(settings, digest)]
        assert stored["body"] == compressor.data
        assert stored["content_type"] == "audio/ogg"

    async def test_the_encoder_is_fed_the_buffer_and_the_declared_format(
        self, service, r2, settings, provider, compressor
    ):
        """§10.1 feeds raw PCM with explicit parameters, and those parameters
        come from `pcm_format()` — the same single source as the streaming WAV
        header, so a clip can never be encoded at a rate its header denies."""
        digest = authorize(r2, settings, provider)

        await listen(service, digest)

        (pcm_length, pcm_format, target_format) = compressor.calls[0]
        assert pcm_length == 2 * len(PCM_CHUNK)
        assert pcm_format == provider.pcm_format()
        assert target_format == "ogg-opus"

    async def test_the_receipt_is_written_after_the_audio(
        self, service, r2, settings, provider
    ):
        """§9.3: audio first, receipt last. The audio object's presence is the
        commit — a crash between the two leaves a perfectly playable clip, and
        nothing in the serving waterfall ever reads a receipt."""
        digest = authorize(r2, settings, provider)

        await listen(service, digest)

        keys = list(r2.objects)
        assert keys.index(audio_key(settings, digest)) < keys.index(
            receipt_key(settings, digest)
        )

    async def test_the_receipt_carries_the_container_duration_and_no_text(
        self, service, r2, settings, provider, compressor
    ):
        """§9.3: the receipt is publicly fetchable, so it must carry no text
        and no user identifiers — and its duration is the encoder's measured
        value, which is the only place an exact one exists (§6.2)."""
        digest = authorize(r2, settings, provider)

        await listen(service, digest)

        body = r2.objects[receipt_key(settings, digest)]["body"].decode()
        assert f'"duration_ms": {compressor.duration_ms}' in body
        assert "In the beginning" not in body


class TestSkippingWork:
    async def test_an_already_uploaded_artifact_skips_the_encode_entirely(
        self, service, r2, settings, provider, compressor
    ):
        """§10.1 step 2. Duplicate generations are expected wherever instance
        topology does not pin one hash to one process (B6), and encoding bytes
        that are about to lose a conditional PUT is pure waste.

        `compressor.calls` being empty is the only honest way to assert "never
        reached" — a cheaper-looking check on the stored object would pass even
        if ffmpeg had run.
        """
        digest = authorize(r2, settings, provider)

        # Planted *after* the generation is spawned, not before: an object that
        # already exists at resolve time is answered by rung 2's redirect and
        # no generation happens at all, which would make this test vacuous.
        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream)
        task = resolution.entry.task
        r2.objects[audio_key(settings, digest)] = {
            "body": b"another instance got here first",
            "content_type": "audio/ogg",
        }
        async for _ in resolution.reader():
            pass
        assert task is not None
        await asyncio.wait([task])

        assert compressor.calls == []
        assert r2.objects[audio_key(settings, digest)]["body"] == (
            b"another instance got here first"
        )

    async def test_losing_the_conditional_put_is_success_not_an_error(
        self, service, r2, settings, provider, compressor
    ):
        """§10.1 step 4, first-writer-wins. A loss means a concurrent
        generation stored its own render first; both are valid renders of the
        same recipe (§9.1), so the loser keeps its own readers happy and lets
        the stored one stand.

        Staged by planting the object *after* the HEAD check has passed, which
        is the race the conditional PUT exists for. Note this is a
        storage-dedup guard and not an anti-double-billing one (CB4) — by the
        time we are here, both renders have already been paid for.
        """
        digest = authorize(r2, settings, provider)
        winner = b"the other instance's render"
        original_compress = compressor.compress

        async def plant_then_compress(*args, **kwargs):
            r2.objects[audio_key(settings, digest)] = {
                "body": winner,
                "content_type": "audio/ogg",
            }
            return await original_compress(*args, **kwargs)

        compressor.compress = plant_then_compress

        await listen(service, digest)

        assert r2.objects[audio_key(settings, digest)]["body"] == winner
        # Still written: the receipt describes the recipe, which both renders
        # share, and it is best-effort either way.
        assert receipt_key(settings, digest) in r2.objects


class TestFailuresNeverCostTheClip:
    async def test_a_failed_encode_leaves_the_clip_regenerable(
        self, r2, settings, provider
    ):
        """No object, no receipt, no exception out of the generation task —
        and the sidecar is untouched, so the next `get-audio` simply makes it
        again (§7.2 rung 4)."""
        service = TtsService(
            settings=settings,
            store=TtsArtifactStore(
                client=r2,
                bucket=settings.r2_tts_bucket or "bucket",
                prefix=settings.tts_r2_prefix,
            ),
            provider=provider,
            compressor=FakeCompressor(failure_type=RuntimeError),
        )
        digest = authorize(r2, settings, provider)

        await listen(service, digest)

        assert audio_key(settings, digest) not in r2.objects
        assert receipt_key(settings, digest) not in r2.objects
        assert f"{settings.tts_r2_prefix}requests/{digest}.json" in r2.objects

    async def test_a_failed_tail_does_not_fail_the_generation_task(
        self, r2, settings, provider
    ):
        """The governing rule of this module, made assertable.

        By the time the tail runs, `mark_complete` has fired and every listener
        has the whole verse — so an exception escaping here would buy nothing
        and cost something: the detached task would end in failure, and the
        done-callback would report a clip that actually worked as an unhandled
        error. The task must finish clean.
        """
        service = TtsService(
            settings=settings,
            store=TtsArtifactStore(
                client=r2,
                bucket=settings.r2_tts_bucket or "bucket",
                prefix=settings.tts_r2_prefix,
            ),
            provider=provider,
            compressor=FakeCompressor(failure_type=RuntimeError),
        )
        digest = authorize(r2, settings, provider)

        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream)
        task = resolution.entry.task
        assert task is not None
        async for _ in resolution.reader():
            pass
        await asyncio.wait([task])

        assert task.exception() is None
        assert resolution.entry.state == "complete"  # not retroactively failed

    async def test_a_failed_receipt_does_not_fail_the_artifact(
        self, service, r2, settings, provider
    ):
        """§9.3: nothing may require the receipt. If a cosmetic write could
        fail an artifact, this design would have re-earned the stuck-lock
        failure mode the whole store was built to avoid."""
        digest = authorize(r2, settings, provider)
        original_put = r2.put_object

        def fail_receipts(**kwargs):
            if kwargs["Key"].endswith(".json") and "receipts/" in kwargs["Key"]:
                raise RuntimeError("receipt write failed")
            return original_put(**kwargs)

        r2.put_object = fail_receipts

        await listen(service, digest)

        assert audio_key(settings, digest) in r2.objects
        assert receipt_key(settings, digest) not in r2.objects


class TestAccounting:
    async def test_the_entry_drains_and_its_bytes_come_back(
        self, service, r2, settings, provider
    ):
        """§9.2. The slot is released when the buffer is, by refcount — so
        "the tail finished" and "the memory came back" are the same event only
        once every reader has let go.
        """
        digest = authorize(r2, settings, provider)
        before = service.heap.buffered_bytes

        await listen(service, digest)

        assert service.heap.get(digest) is None  # out of the primary dict
        assert service.heap.buffered_bytes == before
