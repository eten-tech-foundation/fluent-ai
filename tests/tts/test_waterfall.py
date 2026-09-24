"""
tests/tts/test_waterfall.py — `resolve_audio`'s rung order (§7.2, §9.2).

The waterfall is exercised at the service layer rather than over HTTP for one
practical reason: several of its rules are about what happens *while* a clip is
still streaming (a second listener attaching, a draining entry losing to a
freshly-uploaded compressed object), and httpx's ASGI transport buffers a whole
response before returning it, so a held-open stream cannot be staged from the
client side. The HTTP surface of these same paths is covered in
`tests/api/v1/test_tts_audio.py`.
"""

import asyncio
import gc

import pytest

from app.errors.exceptions import (
    ExternalServiceException,
    NotFoundException,
    ServiceUnavailableException,
)
from app.errors.codes import ErrorCode
from app.schemas.tts import TtsGenerateRequest
from app.services.tts.artifacts import TtsArtifactStore, serialize_json_body
from app.services.tts.generation import GenerationFailed
from app.services.tts.recipe import artifact_hash, build_recipe
from app.services.tts.service import AudioRedirect, AudioStream, TtsService
from app.services.tts.wav import WAV_HEADER_BYTES
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
def compressor() -> FakeCompressor:
    return FakeCompressor()


@pytest.fixture
def settings():
    return tts_settings(tts_admission_wait_seconds=0.05)


@pytest.fixture
def service_without_tail(r2, provider, settings) -> TtsService:
    """A service whose compression tail always fails.

    Two rungs are only reachable when no compressed object exists, and since
    phase 08 the tail uploads one on every completed generation — so the way
    to reach them is a tail that could not produce the object (encoder down,
    R2 refusing). Faking *that* keeps those tests about the waterfall while
    also pinning the tail's failure contract: a clip stays attachable and
    regenerable rather than becoming a 404.
    """
    return TtsService(
        settings=settings,
        store=TtsArtifactStore(
            client=r2,
            bucket=settings.r2_tts_bucket or "bucket",
            prefix=settings.tts_r2_prefix,
        ),
        provider=provider,
        compressor=FakeCompressor(failure_type=RuntimeError),
    )


@pytest.fixture
def service(r2, provider, settings, compressor) -> TtsService:
    store = TtsArtifactStore(
        client=r2,
        bucket=settings.r2_tts_bucket or "bucket",
        prefix=settings.tts_r2_prefix,
    )
    return TtsService(
        settings=settings, store=store, provider=provider, compressor=compressor
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


def compress(r2, settings, digest: str, extension: str = "ogg") -> None:
    """Put a compressed object in R2 without running a generation.

    Still useful after phase 08 built the real tail: several rungs need the
    object to exist for a hash that this process never synthesized — which is
    the ordinary case of another instance having done the work (§10.1).
    """
    r2.objects[f"{settings.tts_r2_prefix}audio/{digest}.{extension}"] = {
        "body": b"compressed bytes",
        "content_type": "audio/ogg",
    }


def audio_object(r2, settings, digest: str, extension: str = "ogg"):
    """The stored compressed artifact for `digest`, or None."""
    return r2.objects.get(f"{settings.tts_r2_prefix}audio/{digest}.{extension}")


async def drain(stream: AudioStream) -> bytes:
    return b"".join([chunk async for chunk in stream.reader()])


async def drain_and_settle(stream: AudioStream) -> bytes:
    """Read the clip AND wait for its generation task to finish the tail.

    Draining a reader is not the same event as the generation finishing. The
    reader has every byte once `state` flips to `complete`, but the task then
    runs the compression tail (§10.1) — HEAD, encode, conditional PUT, receipt
    — and only *afterwards* moves the entry to the draining set. So a test that
    stopped at the reader would be racing the upload it means to assert about.

    Awaiting the task is the deterministic wait; a sleep would be a guess.
    Captured before draining because the done-callback clears `entry.task` to
    break the entry/traceback cycle (§8.3, N1).
    """
    task = stream.entry.task
    data = await drain(stream)
    if task is not None:
        await asyncio.wait([task])
    return data


async def listen_once(service: TtsService, digest: str) -> None:
    """Play a clip to the end and leave no reference to its entry behind."""
    resolution = await service.resolve_audio(digest)
    assert isinstance(resolution, AudioStream)
    await drain_and_settle(resolution)


# ---------------------------------------------------------------------------
# Rung order (§7.2)
# ---------------------------------------------------------------------------


class TestRungOrder:
    async def test_nothing_authorized_is_the_404_rung(self, service, provider):
        with pytest.raises(NotFoundException) as excinfo:
            await service.resolve_audio("0" * 64)

        assert excinfo.value.code == ErrorCode.TTS_ARTIFACT_NOT_FOUND
        assert provider.synthesize_calls == []

    async def test_a_sidecar_alone_spawns_a_generation(
        self, service, r2, settings, provider
    ):
        digest = authorize(r2, settings, provider)

        resolution = await service.resolve_audio(digest)

        assert isinstance(resolution, AudioStream)
        assert await drain(resolution) == (resolution.header + PCM_CHUNK * 2)
        assert len(provider.synthesize_calls) == 1
        # Regeneration works from durable state alone — which is what makes any
        # replica able to serve an artifact it has never seen (§7.2 rung 3).
        assert provider.synthesize_calls[0].text == "In the beginning"
        assert provider.synthesize_calls[0].model == "test-tts-model"

    async def test_the_compressed_object_wins_over_a_new_generation(
        self, service, r2, settings, provider
    ):
        digest = authorize(r2, settings, provider)
        compress(r2, settings, digest)

        resolution = await service.resolve_audio(digest)

        assert isinstance(resolution, AudioRedirect)
        assert resolution.location.endswith(f"/tts/audio/{digest}.ogg")
        assert provider.synthesize_calls == []

    async def test_an_in_flight_entry_wins_over_everything(
        self, service, r2, settings, provider
    ):
        """Rung 1 is checked before R2 is touched at all: a listener joining a
        clip mid-synthesis must hear that clip, not be redirected to an object
        that appeared moments ago."""
        digest = authorize(r2, settings, provider)
        provider.paced = True
        first = await service.resolve_audio(digest)
        compress(r2, settings, digest)  # phase 08 finishes for another replica
        r2.head_calls.clear()  # the ledger from the first resolution

        second = await service.resolve_audio(digest)

        assert isinstance(second, AudioStream)
        assert second.entry is first.entry
        assert r2.head_calls == []  # rung 1 short-circuits before any HEAD
        provider.release(2)

    async def test_a_missing_public_base_url_is_a_clean_503_not_a_none_url(
        self, r2, provider
    ):
        """A redirect to a 'None'-prefixed host would be a broken clip the
        client cannot classify; 503 is a state it already knows how to wait
        out."""
        settings = tts_settings(tts_public_audio_base_url=None)
        store = TtsArtifactStore(client=r2, bucket="b", prefix=settings.tts_r2_prefix)
        service = TtsService(
            settings=settings,
            store=store,
            provider=provider,
            compressor=FakeCompressor(),
        )
        digest = authorize(r2, settings, provider)
        compress(r2, settings, digest)

        with pytest.raises(ServiceUnavailableException) as excinfo:
            await service.resolve_audio(digest)

        assert excinfo.value.code == ErrorCode.TTS_STORAGE_NOT_CONFIGURED
        assert excinfo.value.retry_after is None  # waiting will not help


# ---------------------------------------------------------------------------
# The draining set (§9.2)
# ---------------------------------------------------------------------------


class TestDrainingSet:
    async def test_a_draining_entry_serves_attach_while_the_object_is_absent(
        self, service_without_tail, r2, settings, provider
    ):
        """§12.3: a finished-but-still-draining entry is a legitimate source
        for a new listener — but only until the compressed object exists.

        **Staged through a failed tail, which is now the only way to reach
        this state.** Before phase 08 nothing was ever uploaded, so "draining
        with no compressed object" was simply what draining looked like; now
        the tail uploads on the way out, and the object is absent exactly when
        the tail could not produce it (encoder down, R2 refusing). So this also
        pins the tail's failure contract: the clip stays *attachable* and
        regenerable rather than becoming a 404.
        """
        service = service_without_tail
        digest = authorize(r2, settings, provider)
        first = await service.resolve_audio(digest)
        assert isinstance(first, AudioStream)
        await drain_and_settle(first)  # generation, then the (failing) tail
        assert service.heap.get(digest) is None

        second = await service.resolve_audio(digest)

        assert isinstance(second, AudioStream)
        assert second.entry is first.entry
        assert len(provider.synthesize_calls) == 1  # attached, did not respawn

    async def test_once_compressed_the_redirect_beats_the_draining_entry(
        self, service, r2, settings, provider
    ):
        """The 302 wins: R2 brings Range support, a Content-Length, edge
        caching and about a tenth of the bytes.

        No `compress()` stand-in any more: the tail this test used to fake is
        built, so draining the first listen really does put the object in R2.
        """
        digest = authorize(r2, settings, provider)
        first = await service.resolve_audio(digest)
        assert isinstance(first, AudioStream)
        await drain_and_settle(first)
        assert audio_object(r2, settings, digest) is not None

        second = await service.resolve_audio(digest)

        assert isinstance(second, AudioRedirect)
        assert service.heap.get_draining(digest) is first.entry  # still there

    async def test_a_drained_entry_with_no_readers_falls_through_to_regenerate(
        self, service_without_tail, r2, settings, provider
    ):
        """The draining set holds entries weakly, so 'still draining' means
        'someone is still listening' and nothing else.

        Staged with a failing tail for the same reason as the test above: with
        a working one the second listen would get the 302, which is a different
        rung and already covered.

        The listen happens inside a helper so that *nothing* in this frame
        references the entry afterwards — pytest rewrites assertions into
        temporaries that outlive a `del`, which is enough to keep an entry
        alive and quietly turn this into a test of pytest's internals.
        """
        service = service_without_tail
        digest = authorize(r2, settings, provider)
        await listen_once(service, digest)

        gc.collect()
        await asyncio.sleep(0)
        assert service.heap.get_draining(digest) is None
        second = await service.resolve_audio(digest)

        assert isinstance(second, AudioStream)
        # Drained, not just resolved: `synthesize_stream` is an async generator,
        # so the provider is not touched until the task pulls its first chunk.
        assert await drain_and_settle(second) == second.header + PCM_CHUNK * 2
        assert len(provider.synthesize_calls) == 2


# ---------------------------------------------------------------------------
# Dedup and admission (§9.2, T25)
# ---------------------------------------------------------------------------


class TestDedupAndAdmission:
    async def test_concurrent_first_listens_make_one_provider_call(
        self, service, r2, settings, provider
    ):
        """The dedup promise: a double-clicked play button, or two React
        effects, cost one generation and one billing event."""
        digest = authorize(r2, settings, provider)
        provider.paced = True

        resolutions = await asyncio.gather(
            *(service.resolve_audio(digest) for _ in range(5))
        )

        entries = {id(r.entry) for r in resolutions}
        assert len(entries) == 1
        assert len(provider.synthesize_calls) == 1
        assert service.heap.buffered_bytes == service.heap.max_clip_bytes
        provider.release(2)

    async def test_attaching_does_not_consume_an_admission_slot(
        self, service, r2, settings, provider
    ):
        digest = authorize(r2, settings, provider)
        provider.paced = True
        await service.resolve_audio(digest)
        await asyncio.sleep(0)  # let the detached task reach the provider
        # Take every remaining slot, so nothing new could possibly be admitted.
        held = [
            (
                await service.heap.admit(f"{'f' * 63}{i}", TtsGenerateRequest(text="x"))
            ).entry
            for i in range(service.heap.slots - 1)
        ]

        attached = await service.resolve_audio(digest)

        assert isinstance(attached, AudioStream)
        assert len(provider.synthesize_calls) == 1
        assert len(held) == service.heap.slots - 1
        provider.release(2)

    async def test_a_302_is_served_even_when_the_budget_is_full(
        self, service, r2, settings, provider
    ):
        """Redirects and 404s bypass the cap too — neither allocates a byte."""
        digest = authorize(r2, settings, provider)
        compress(r2, settings, digest)
        held = [
            (
                await service.heap.admit(f"{'f' * 63}{i}", TtsGenerateRequest(text="x"))
            ).entry
            for i in range(service.heap.slots)
        ]

        assert isinstance(await service.resolve_audio(digest), AudioRedirect)
        with pytest.raises(NotFoundException):
            await service.resolve_audio("0" * 64)
        assert len(held) == service.heap.slots


# ---------------------------------------------------------------------------
# Failure (§7.2.1, §8.3)
# ---------------------------------------------------------------------------


class TestFailure:
    async def test_a_failed_generation_aborts_readers_and_frees_its_slot(
        self, service, r2, settings, provider
    ):
        """The whole failure contract in one test: the reader aborts rather
        than ending, the entry is dropped so the client's retry re-enters
        through admission, and the slot comes back with the buffer."""
        digest = authorize(r2, settings, provider)
        provider.fail_after = 1
        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream)

        received = []
        with pytest.raises(GenerationFailed) as excinfo:
            async for chunk in resolution.reader():
                received.append(chunk)

        assert received == [resolution.header, PCM_CHUNK]  # heard, then cut off
        assert len(received[0]) == WAV_HEADER_BYTES
        assert service.heap.get(digest) is None
        assert len(provider.synthesize_calls) == 1  # no server-side retry

        # The abort's traceback holds the reader's frame, which holds the entry
        # — so a failed clip's buffer lives exactly as long as its traceback
        # does (here, this test's `excinfo`; in production, one log record).
        # Dropping it is what lets the finalizer return the bytes.
        excinfo.value.__traceback__ = None
        del excinfo, resolution
        gc.collect()
        await asyncio.sleep(0)
        assert service.heap.buffered_bytes == 0

    async def test_the_done_callback_leaves_no_exception_object_behind(
        self, service, r2, settings, provider
    ):
        """N1: `entry.task` is cleared and the failure is recorded as a string.
        Keeping the exception would chain entry -> task -> traceback -> frame ->
        entry, and park the buffer's release on the cyclic collector exactly
        when failed entries are piling up."""
        digest = authorize(r2, settings, provider)
        provider.fail_after = 0
        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream)
        entry = resolution.entry

        with pytest.raises(GenerationFailed):
            await drain(resolution)
        await asyncio.sleep(0)  # the done-callback runs via loop.call_soon

        assert entry.task is None
        assert entry.state == "failed"
        assert isinstance(entry.error, str)
        assert entry.error == "RuntimeError"

    async def test_a_second_listener_after_a_failure_regenerates(
        self, service, r2, settings, provider
    ):
        """No server-side retry means the *client* re-enters through admission,
        which is what keeps the RAM budget in charge of pacing during provider
        trouble (§8.3)."""
        digest = authorize(r2, settings, provider)
        provider.fail_after = 0
        first = await service.resolve_audio(digest)
        with pytest.raises(GenerationFailed):
            await drain(first)

        provider.fail_after = None
        second = await service.resolve_audio(digest)

        assert isinstance(second, AudioStream)
        assert await drain_and_settle(second) == second.header + PCM_CHUNK * 2
        assert len(provider.synthesize_calls) == 2

    async def test_a_stream_over_the_per_clip_ceiling_aborts(
        self, r2, provider, settings
    ):
        """§9.2's per-clip ceiling: a clip growing past the largest legitimate
        verse is killed rather than allowed to spend its neighbours' memory.

        The code is its own, not the provider's: `TTS_CLIP_TOO_LONG` says audio
        was already being billed and streamed when it outgrew the ceiling,
        where `TTS_TEXT_TOO_LONG` means `generate` refused before any spend."""
        settings = tts_settings(tts_max_clip_bytes=len(PCM_CHUNK) + 1)
        store = TtsArtifactStore(client=r2, bucket="b", prefix=settings.tts_r2_prefix)
        service = TtsService(
            settings=settings,
            store=store,
            provider=provider,
            compressor=FakeCompressor(),
        )
        digest = authorize(r2, settings, provider)

        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream)
        with pytest.raises(GenerationFailed):
            await drain(resolution)

        assert resolution.entry.error == ErrorCode.TTS_CLIP_TOO_LONG
        assert len(resolution.entry.buffer) <= settings.tts_max_clip_bytes

    async def test_attaching_to_an_already_failed_entry_is_a_502(
        self, service, r2, settings, provider
    ):
        """§8.3's named case: a generation that failed before its reader got
        any headers can still be answered properly, so it is — with 502
        TTS_PROVIDER_UNAVAILABLE rather than an abort."""
        digest = authorize(r2, settings, provider)
        entry, _ = await service.heap.admit(digest, TtsGenerateRequest(text="x"))
        await entry.mark_failed("TTS_PROVIDER_UNAVAILABLE")

        with pytest.raises(ExternalServiceException) as excinfo:
            await service.resolve_audio(digest)

        assert excinfo.value.status_code == 502
        assert excinfo.value.code == ErrorCode.TTS_PROVIDER_UNAVAILABLE


# ---------------------------------------------------------------------------
# Shutdown (§8.3)
# ---------------------------------------------------------------------------


class TestShutdown:
    """SIGTERM, from the listener's side and from the budget's.

    There is deliberately no drain-and-finish: a clip completed after every
    listener's connection has died costs provider money to produce for nobody,
    and the request sidecar on R2 means the restarted process — or any other
    replica — regenerates on the next request.
    """

    async def test_shutdown_aborts_a_live_listener_and_drops_the_entry(
        self, service, r2, settings, provider
    ):
        digest = authorize(r2, settings, provider)
        provider.paced = True
        resolution = await service.resolve_audio(digest)
        assert isinstance(resolution, AudioStream)
        entry, task = resolution.entry, resolution.entry.task
        reader = resolution.reader()
        assert await anext(reader) == resolution.header
        provider.release()
        # Mid-clip when the signal lands: bytes already heard, more expected.
        assert await anext(reader) == PCM_CHUNK

        await service.shutdown()

        with pytest.raises(GenerationFailed) as excinfo:
            await anext(reader)
        # T22 again: the abort *is* the signal. Ending politely here would hand
        # the listener a truncated verse indistinguishable from a short one.
        assert excinfo.value.reason == "cancelled"
        assert entry.state == "failed"
        assert task is not None and task.cancelled()
        # Dropped, so the client's retry against the restarted process (or
        # another replica) re-enters through admission (§8.3).
        assert service.heap.get(digest) is None

    async def test_shutdown_gives_the_admission_slot_back(
        self, service, r2, settings, provider
    ):
        """The accounting half. `CancelledError` is what runs the teardown that
        releases the buffer — abandon the task instead and the bytes stay
        reserved until the process dies."""
        digest = authorize(r2, settings, provider)
        provider.paced = True
        resolution = await service.resolve_audio(digest)
        await asyncio.sleep(0)  # let the detached task reach the provider
        assert service.heap.buffered_bytes == service.heap.max_clip_bytes

        del resolution  # the listener's connection dies with the process
        await service.shutdown()
        gc.collect()
        await asyncio.sleep(0)  # the semaphore release is scheduled on the loop

        assert service.heap.buffered_bytes == 0

    async def test_shutdown_with_nothing_in_flight_is_quiet(self, service):
        await service.shutdown()

        assert service.heap.buffered_bytes == 0


# ---------------------------------------------------------------------------
# generate's short-circuit (§7.1, amended 2026-08-20)
# ---------------------------------------------------------------------------


class TestGenerateShortCircuit:
    """`generate` answers with the compressed object's URL when one exists.

    These live beside the waterfall rather than in `test_service.py` because
    the behaviour IS a waterfall rung: `generate` now answers the same question
    rung 2 answers, one round trip earlier. Before this, a fully cached verse
    cost the browser three hops — `generate`, `get-audio` (which read the
    sidecar and HEADed the object only to redirect), and finally R2. Answering
    at `generate` collapses that to two and skips the sidecar read entirely.

    The margin of error is deliberate and one-directional: an artifact
    compressed BETWEEN this call and the first GET is still reported as
    streaming, so the caller can under-report a cache hit but never over-report
    one — objects are immutable and never evicted (§9.4), so a URL handed out
    here cannot stop resolving.
    """

    async def test_a_first_generate_asks_r2_nothing_extra(self, service, r2):
        """The optimisation that keeps `generate` cheap (T8).

        A sidecar this call WROTE cannot have been compressed yet — nothing has
        ever listened to it — so there is nothing to look for, and the HEAD is
        skipped rather than spent on a guaranteed miss.
        """
        response = await service.generate(TtsGenerateRequest(text="In the beginning"))

        assert response.audio_url.endswith(".wav")
        assert not response.audio_url.startswith("http")
        assert r2.head_calls == []

    async def test_a_repeat_generate_with_nothing_compressed_still_streams(
        self, service, r2, settings, provider
    ):
        authorize(r2, settings, provider, text="In the beginning")

        response = await service.generate(TtsGenerateRequest(text="In the beginning"))

        assert (
            response.audio_url
            == f"audio/{artifact_hash(build_recipe(TtsGenerateRequest(text='In the beginning'), settings=settings, provider=provider), secret=settings.tts_hash_secret)}.wav"
        )
        # The sidecar already existed, so the object was worth looking for.
        assert len(r2.head_calls) == 1

    async def test_a_repeat_generate_returns_the_absolute_bucket_url(
        self, service, r2, settings, provider
    ):
        digest = authorize(r2, settings, provider, text="In the beginning")
        compress(r2, settings, digest)

        response = await service.generate(TtsGenerateRequest(text="In the beginning"))

        assert response.audio_url == f"https://tts.example.test/tts/audio/{digest}.ogg"

    async def test_the_returned_url_carries_the_recipe_format(
        self, r2, provider, compressor
    ):
        """The extension is the recipe's, not a constant — which is the whole
        reason a caller can read the format off the URL at all."""
        settings = tts_settings(tts_default_format="mp3")
        store = TtsArtifactStore(client=r2, bucket="b", prefix=settings.tts_r2_prefix)
        service = TtsService(
            settings=settings, store=store, provider=provider, compressor=compressor
        )
        digest = authorize(r2, settings, provider, text="In the beginning")
        compress(r2, settings, digest, extension="mp3")

        response = await service.generate(TtsGenerateRequest(text="In the beginning"))

        assert response.audio_url.endswith(f"{digest}.mp3")

    async def test_an_unconfigured_public_base_url_falls_back_and_does_not_raise(
        self, r2, provider, compressor
    ):
        """`resolve_audio` turns this into a 503 the client can wait out, but
        `generate` must not fail for a storage reason — it spends nothing and
        its whole job is to authorize. The relative URL still works; the 503
        then happens later, at the redirect, exactly as it did before."""
        settings = tts_settings(tts_public_audio_base_url=None)
        store = TtsArtifactStore(client=r2, bucket="b", prefix=settings.tts_r2_prefix)
        service = TtsService(
            settings=settings, store=store, provider=provider, compressor=compressor
        )
        digest = authorize(r2, settings, provider, text="In the beginning")
        compress(r2, settings, digest)

        response = await service.generate(TtsGenerateRequest(text="In the beginning"))

        assert response.audio_url == f"audio/{digest}.wav"
