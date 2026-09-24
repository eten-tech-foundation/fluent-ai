"""
tests/tts/test_generation.py — the generation heap, its readers, and the RAM
budget (source-tts proposal §7.2.1, §9.2; T21/T25).

These are the phase's load-bearing invariants, so they are asserted directly on
the heap rather than through HTTP: how many slots a budget buys, that a slot
comes back exactly when the bytes do, and that a failed generation reaches its
readers as an abort instead of a polite end.
"""

import asyncio
import gc
import struct

import pytest

from app.errors.exceptions import ServiceUnavailableException
from app.errors.codes import ErrorCode
from app.services.tts.generation import (
    GenerationBuffer,
    GenerationEntry,
    GenerationFailed,
    GenerationHeap,
)
from app.services.tts.provider import PcmFormat
from app.services.tts.recipe import TtsRecipe
from app.services.tts.wav import UNKNOWN_SIZE, WAV_HEADER_BYTES, streaming_wav_header


MIB = 1024 * 1024
# A test-local ceiling, not the shipped default (which is 4x the longest verse,
# 8.8 MB — see config.py's sizing block). Round numbers here keep the slot
# arithmetic below readable.
CLIP_CEILING = 30 * MIB


def recipe(text: str = "In the beginning") -> TtsRecipe:
    return TtsRecipe(text=text, model="test-tts-model", format="ogg-opus")


def heap(**overrides) -> GenerationHeap:
    kwargs = {
        "max_buffered_bytes": 256 * MIB,
        "max_clip_bytes": CLIP_CEILING,
        "admission_wait_seconds": 0.05,
        "retry_after_seconds": 5,
    }
    kwargs.update(overrides)
    return GenerationHeap(**kwargs)  # type: ignore[arg-type]


async def drain_reader(entry: GenerationEntry, **overrides) -> bytes:
    kwargs = {"header": b"HDR", "max_seconds": 5.0}
    kwargs.update(overrides)
    return b"".join([chunk async for chunk in entry.read(**kwargs)])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The streaming WAV header (§7.2.1, T22)
# ---------------------------------------------------------------------------


class TestStreamingWavHeader:
    def test_sizes_are_the_unknown_length_sentinel(self):
        """The two size fields are `0xFFFFFFFF` and are never backfilled — a
        chunked response has nothing to seek back to, and this is what makes an
        abort the only honest failure signal (§7.2.1)."""
        header = streaming_wav_header(PcmFormat(24000, 1, 16))

        assert len(header) == WAV_HEADER_BYTES
        assert header[:4] == b"RIFF"
        assert header[8:12] == b"WAVE"
        riff_size = struct.unpack("<I", header[4:8])[0]
        data_size = struct.unpack("<I", header[40:44])[0]
        assert riff_size == data_size == UNKNOWN_SIZE == 0xFFFFFFFF

    def test_format_fields_come_from_the_provider_declaration(self):
        """A header that disagrees with the bytes behind it is a clip that
        plays at the wrong pitch — inaudible to any assertion but the header's
        own."""
        header = streaming_wav_header(PcmFormat(24000, 1, 16))
        channels, rate, byte_rate, block_align, bits = struct.unpack(
            "<HIIHH", header[22:36]
        )

        assert (channels, rate, bits) == (1, 24000, 16)
        assert byte_rate == 48000  # 24 kHz x 1 x 2 bytes — §9.2's ~48 KB/s
        assert block_align == 2

    def test_a_different_provider_format_produces_a_different_header(self):
        stereo = streaming_wav_header(PcmFormat(48000, 2, 16))
        channels, rate, byte_rate = struct.unpack("<HII", stereo[22:32])
        assert (channels, rate, byte_rate) == (2, 48000, 192000)


# ---------------------------------------------------------------------------
# Admission and accounting (§9.2, T25)
# ---------------------------------------------------------------------------


class TestAdmission:
    def test_slots_are_worst_case_byte_reservations(self):
        """§8.4's arithmetic, asserted: 256 MiB / ~31 MB per clip = 8 slots.
        A count semaphore IS the byte gate once each count is worth the
        per-clip ceiling."""
        assert heap().slots == 8
        assert heap(max_buffered_bytes=64 * MIB).slots == 2

    def test_a_budget_under_one_clip_still_admits_one(self):
        """Refusing everything would be a worse failure than briefly exceeding
        a misconfigured budget; the constructor logs a warning instead."""
        assert heap(max_buffered_bytes=1024).slots == 1

    async def test_admission_reserves_the_ceiling_not_the_actual_size(self):
        h = heap()
        entry, created = await h.admit("a" * 64, recipe())

        assert created
        # Nothing has been synthesized yet, and the reservation is already the
        # full worst case — that is what makes the budget a guarantee rather
        # than a hope.
        assert len(entry.buffer) == 0
        assert h.buffered_bytes == CLIP_CEILING

    async def test_over_budget_is_a_503_with_retry_after(self):
        """§12.3: byte cap exceeded ⇒ brief wait, then 503 + Retry-After. The
        raise happens while resolving, before any response object exists, which
        is what makes 'before any body bytes' structural."""
        h = heap(max_buffered_bytes=CLIP_CEILING)  # exactly one slot
        held, _ = await h.admit("a" * 64, recipe())

        with pytest.raises(ServiceUnavailableException) as excinfo:
            await h.admit("b" * 64, recipe())

        assert excinfo.value.status_code == 503
        assert excinfo.value.code == ErrorCode.TTS_BUSY
        assert excinfo.value.retry_after == 5
        assert held is not None  # keep the slot held for the duration

    async def test_concurrent_admissions_never_exceed_the_budget(self):
        """The cap-boundary case from §12.3: more contenders than slots, and
        the counter must never read above the budget."""
        budget = 4 * CLIP_CEILING
        h = heap(max_buffered_bytes=budget, admission_wait_seconds=0.01)
        peak = 0

        async def admit(index: int):
            nonlocal peak
            try:
                entry, _ = await h.admit(f"{index:064d}", recipe())
            except ServiceUnavailableException:
                return None
            peak = max(peak, h.buffered_bytes)
            return entry

        entries = await asyncio.gather(*(admit(i) for i in range(10)))

        admitted = [entry for entry in entries if entry is not None]
        assert len(admitted) == 4  # the other six were refused, by design
        assert peak == budget
        assert h.buffered_bytes <= budget

    async def test_two_requests_queued_for_one_hash_still_make_one_entry(self):
        """The dedup guard has to survive *waiting*, which is the case a quick
        concurrency test misses entirely: when slots are free, `acquire()`
        never suspends, so the first check catches everything. Under real
        contention two requests for one verse both queue, both wake when slots
        free, and only the check *after* the wait stops the second from
        clobbering the first's entry — one verse, two entries, two provider
        calls, two bills.
        """
        h = heap(max_buffered_bytes=2 * CLIP_CEILING, admission_wait_seconds=5.0)
        holders = [(await h.admit(f"{i}" * 64, recipe())).entry for i in range(2)]
        assert h.buffered_bytes == 2 * CLIP_CEILING  # every slot spoken for

        artifact = "a" * 64
        queued = [
            asyncio.create_task(h.admit(artifact, recipe())),
            asyncio.create_task(h.admit(artifact, recipe())),
        ]
        await asyncio.sleep(0.01)  # both are now waiting on the semaphore

        # Popped rather than iterated: a `for holder in holders` loop leaves
        # `holder` bound in this frame afterwards, which keeps one buffer — and
        # so one slot's worth of budget — alive and makes the assertion below
        # read 60 MiB. The accounting is refcount-exact, so tests have to be
        # exact about references too.
        while holders:
            h.drain(holders.pop())  # their clips finished and readers let go
        gc.collect()
        await asyncio.sleep(0)
        first, second = await asyncio.gather(*queued)

        assert first.entry is second.entry
        assert [first.created, second.created] == [True, False]
        # One entry means one reservation: the loser handed its slot straight
        # back instead of holding a second clip's worth of budget hostage.
        assert h.buffered_bytes == CLIP_CEILING

    async def test_a_queued_request_that_times_out_attaches_instead_of_503ing(self):
        """Refusing a request whose clip started while it queued would be a
        503 for audio that is already being synthesized."""
        h = heap(max_buffered_bytes=CLIP_CEILING, admission_wait_seconds=0.05)
        holder = (await h.admit("b" * 64, recipe())).entry
        artifact = "a" * 64

        queued = asyncio.create_task(h.admit(artifact, recipe()))
        await asyncio.sleep(0)
        # Another request wins the entry while this one is stuck in the queue.
        winner = GenerationEntry(
            artifact=artifact, recipe=recipe(), buffer=GenerationBuffer()
        )
        h._entries[artifact] = winner  # noqa: SLF001 - staging the race

        result = await queued

        assert result.entry is winner
        assert result.created is False
        assert holder.state == "generating"

    async def test_the_slot_is_released_only_when_the_buffer_is_freed(self):
        """§12.3's finalizer-accounting case. The release rides
        `weakref.finalize` on the buffer, so it happens when the memory does —
        not when the task ends, and not at the next cyclic GC."""
        h = heap(max_buffered_bytes=CLIP_CEILING)
        entry, created = await h.admit("a" * 64, recipe())
        h.drain(entry)

        # Still held: the entry (and its buffer) is alive in this frame, which
        # is exactly the state a slow reader keeps it in.
        assert h.buffered_bytes == CLIP_CEILING

        del entry
        gc.collect()
        # The finalizer only schedules work; counter and semaphore change
        # together on the event loop, with no lock held during GC.
        assert h.buffered_bytes == CLIP_CEILING
        await asyncio.sleep(0)  # the semaphore release is scheduled on the loop

        assert h.buffered_bytes == 0
        readmitted, created = await h.admit("b" * 64, recipe())
        assert created and readmitted.state == "generating"


# ---------------------------------------------------------------------------
# Registry transitions (§9.2)
# ---------------------------------------------------------------------------


class TestRegistry:
    async def test_a_drained_entry_is_served_only_while_a_reader_holds_it(self):
        h = heap()
        entry, created = await h.admit("a" * 64, recipe())
        h.drain(entry)

        assert h.get("a" * 64) is None  # out of the primary dict
        assert h.get_draining("a" * 64) is entry

        del entry
        gc.collect()
        # The draining set holds entries *weakly*: with no reader left there is
        # nothing to drain, and the hash falls through to R2 on the next look.
        assert h.get_draining("a" * 64) is None

    async def test_discard_never_evicts_a_newer_entry_for_the_same_hash(self):
        """A failed generation drops out and the client retries — by then a new
        entry may already be registered, and evicting by key alone would kill a
        healthy generation other readers are listening to."""
        h = heap()
        artifact = "a" * 64
        stale, _ = await h.admit(artifact, recipe())
        h.discard(stale)
        fresh, _ = await h.admit(artifact, recipe())

        h.discard(stale)  # late callback from the first generation

        assert h.get(artifact) is fresh


# ---------------------------------------------------------------------------
# Readers (§7.2.1, T22)
# ---------------------------------------------------------------------------


class TestReader:
    async def test_the_stream_grows_with_the_buffer(self):
        """A reader parked at end-of-buffer wakes on the writer's notify and
        yields only what it has not sent — which is what a first listener
        hearing a verse while it is synthesized actually depends on."""
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )
        reader = entry.read(header=b"HDR", max_seconds=5.0)

        assert await anext(reader) == b"HDR"

        await entry.append(b"first")
        assert await anext(reader) == b"first"

        await entry.append(b"second")
        assert await anext(reader) == b"second"

        await entry.mark_complete()
        with pytest.raises(StopAsyncIteration):
            await anext(reader)

    async def test_complete_mid_read_finishes_cleanly(self):
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )

        async def write():
            for chunk in (b"one", b"two", b"three"):
                await entry.append(chunk)
                await asyncio.sleep(0)
            await entry.mark_complete()

        streamed, _ = await asyncio.gather(drain_reader(entry), write())
        assert streamed == b"HDRonetwothree"

    async def test_a_late_reader_gets_the_whole_buffer_from_the_start(self):
        """Attaching to a finished (draining) entry must replay everything, not
        just what arrives next — otherwise a second listener hears a verse that
        starts in the middle."""
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )
        await entry.append(b"already here")
        await entry.mark_complete()

        assert await drain_reader(entry) == b"HDRalready here"

    async def test_failure_mid_read_aborts_instead_of_ending(self):
        """T22, the rule this whole phase is built around: a truncated WAV that
        ends politely is indistinguishable from a short verse, so failure must
        break the connection. A clean `StopAsyncIteration` here would be the
        bug."""
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )
        reader = entry.read(header=b"HDR", max_seconds=5.0)
        await anext(reader)
        await entry.append(b"half a verse")
        assert await anext(reader) == b"half a verse"

        await entry.mark_failed("TTS_PROVIDER_UNAVAILABLE")

        with pytest.raises(GenerationFailed) as excinfo:
            await anext(reader)
        assert excinfo.value.reason == "TTS_PROVIDER_UNAVAILABLE"

    async def test_bytes_written_before_a_failure_are_still_delivered_then_aborted(
        self,
    ):
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )
        await entry.append(b"partial")
        await entry.mark_failed("boom")

        received = []
        with pytest.raises(GenerationFailed):
            async for chunk in entry.read(header=b"HDR", max_seconds=5.0):
                received.append(chunk)

        # The listener heard what existed; the connection then broke rather
        # than pretending the clip had ended.
        assert received == [b"HDR", b"partial"]

    async def test_reader_max_lifetime_fires_and_aborts(self):
        """Bounds how long one slow client can pin a finished buffer and the
        admission slot behind it (§7.2.1)."""
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )

        with pytest.raises(GenerationFailed) as excinfo:
            await drain_reader(entry, max_seconds=0.05)

        assert "max-lifetime" in excinfo.value.reason

    async def test_two_readers_of_one_entry_receive_the_same_bytes(self):
        """The dedup promise seen from the reader side: one buffer, one
        provider call, two independent streams (§9.2)."""
        entry = GenerationEntry(
            artifact="a" * 64, recipe=recipe(), buffer=GenerationBuffer()
        )

        async def write():
            await asyncio.sleep(0)
            await entry.append(b"one verse")
            await entry.mark_complete()

        first, second, _ = await asyncio.gather(
            drain_reader(entry), drain_reader(entry), write()
        )
        assert first == second == b"HDRone verse"


# ---------------------------------------------------------------------------
# Shutdown cancellation (§8.3)
# ---------------------------------------------------------------------------


class TestShutdownCancellation:
    """The mechanics of `cancel_all` only.

    What a cancelled generation *does* on its way out — abort its readers, mark
    the entry failed, drop it and give the bytes back — belongs to the service
    and is asserted there (`tests/tts/test_waterfall.py::TestShutdown`), against
    the real task rather than a stand-in.
    """

    async def test_nothing_in_flight_is_a_no_op(self):
        assert await heap().cancel_all() == 0

    async def test_an_entry_without_a_task_is_not_awaited(self):
        """Draining and failed entries have no task to cancel; a shutdown that
        tried to await one would raise on the way down."""
        h = heap()
        entry, _ = await h.admit("a" * 64, recipe())

        assert entry.task is None
        assert await h.cancel_all() == 0

    async def test_every_in_flight_task_is_cancelled_and_awaited(self):
        """Cancelling without awaiting is the bug this closes: the loop would
        close on tasks suspended mid-write and asyncio would log `Task was
        destroyed but it is pending!` on every deploy that caught one."""
        h = heap()
        running = []
        for index in range(3):
            entry, _ = await h.admit(f"{'a' * 63}{index}", recipe())
            entry.task = asyncio.create_task(
                asyncio.sleep(3600), name=f"tts-generate-{index}"
            )
            running.append(entry.task)
        await asyncio.sleep(0)

        assert await h.cancel_all() == 3

        assert all(task.cancelled() for task in running)

    async def test_a_teardown_that_will_not_finish_does_not_hold_up_shutdown(self):
        """The grace is bounded because the process is going away regardless.
        The only way to reach it is a provider stream whose close is stuck —
        which is why the heap logs those tasks by name instead of waiting."""
        h = heap()
        entry, _ = await h.admit("a" * 64, recipe())
        reached_teardown = asyncio.Event()

        async def close_hangs():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                reached_teardown.set()
                await asyncio.sleep(3600)

        entry.task = asyncio.create_task(close_hangs(), name="tts-generate-stuck")
        await asyncio.sleep(0)

        assert await h.cancel_all(grace_seconds=0.05) == 1

        assert reached_teardown.is_set()
        assert not entry.task.done()  # still stuck, and no longer waited on

        entry.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await entry.task
