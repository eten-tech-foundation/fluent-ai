# src/app/services/tts/generation.py
"""
The in-heap generation entries, their readers, and the RAM budget that gates
them (source-tts proposal §7.2.1, §9.2; T21/T25).

There is no database and no staging directory here either: an artifact being
generated exists as a growing `bytearray` in this process and nothing else. Two
consequences run through everything below.

* **The entry dict is the dedup guard.** A second `get-audio` for a hash that is
  already generating finds the entry and attaches as another reader — one
  provider call, one billing event, two listeners. That is the whole
  deduplication story inside a process (§9.2).
* **A reader can never end cleanly on a failure.** The streamed WAV header
  carries unknown-length sizes (§7.2.1), so a truncated clip that ends politely
  is indistinguishable from a short verse. Failure therefore *raises*, closing
  the connection, and the browser sees a network error.

This module owns memory and bookkeeping only. Who calls the provider, and what
happens after a clip completes, belongs to the service layer.
"""

import asyncio
import threading
import weakref
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple
from weakref import WeakValueDictionary

from app.errors.codes import ErrorCode
from app.errors.exceptions import ServiceUnavailableException
from app.logging.utils import get_logger


if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.tts.recipe import TtsRecipe


logger = get_logger(__name__)


GenerationState = Literal["generating", "complete", "failed"]


class GenerationBuffer(bytearray):
    """A `bytearray` that can be weak-referenced.

    §9.2 prescribes `weakref.finalize(buffer, release, nbytes)` so an admission
    slot is released exactly when the memory is, by refcount, rather than
    whenever the cyclic collector next runs. A plain `bytearray` cannot be the
    target of a weak reference at all (`TypeError` at `weakref.ref`), and a
    subclass is the smallest thing that can: it adds a `__weakref__` slot, 32
    bytes per buffer, and keeps every `bytearray` operation the writer and the
    readers use.

    Do not give this class `__slots__` — that would suppress `__weakref__`
    again and silently take the accounting back to whenever the GC feels like
    it.
    """


class GenerationFailed(Exception):
    """Raised inside a reader's response stream to abort the HTTP connection.

    T22 / §7.2.1: this exception is a *feature*, not an error escaping. It ends
    the response without a terminal chunk, so the client observes a network
    error and can retry, and the partial response self-excludes from every
    cache layer (caches store only complete responses). Returning cleanly here
    would hand the listener a silently truncated verse.
    """

    def __init__(self, artifact: str, reason: str) -> None:
        super().__init__(f"tts generation {artifact} failed: {reason}")
        self.artifact = artifact
        self.reason = reason


class Admission(NamedTuple):
    """What `GenerationHeap.admit` answers.

    `created` is the caller's licence to start a task: exactly one admission
    per hash gets it, so "one entry, one provider call" holds even when several
    requests race for the same verse.
    """

    entry: "GenerationEntry"
    created: bool


@dataclass
class GenerationEntry:
    """One in-flight (or draining) generation.

    Deliberately mutable and deliberately not frozen: it *is* the shared state
    a writer and N readers coordinate through.
    """

    artifact: str
    recipe: "TtsRecipe"
    buffer: GenerationBuffer
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    state: GenerationState = "generating"
    error: str | None = None
    task: asyncio.Task | None = None
    """The detached generation task (§8.3).

    Stored here because asyncio holds only *weak* references to tasks — a task
    nobody keeps is free to be collected mid-flight. The primary dict holds the
    entry, the entry holds the task, and that chain is what keeps a generation
    alive while every reader comes and goes.

    Cleared by the done-callback, which is not tidiness: the retrieved
    exception's traceback references the coroutine frame, which holds `entry`
    as a local, so leaving this set completes an entry -> task -> traceback ->
    frame -> entry cycle and parks the buffer's finalizer on the cyclic GC (N1).
    """

    # ------------------------------------------------------------------ #
    # Writer side
    # ------------------------------------------------------------------ #

    async def append(self, chunk: bytes) -> None:
        """Append synthesized PCM and wake every attached reader."""
        async with self.cond:
            self.buffer.extend(chunk)
            self.cond.notify_all()

    async def mark_complete(self) -> None:
        """Flip to `complete` and wake readers so they finish cleanly."""
        async with self.cond:
            self.state = "complete"
            self.cond.notify_all()

    async def mark_failed(self, reason: str) -> None:
        """Flip to `failed` and wake readers so they abort.

        `reason` is a string by contract, never an exception object: storing
        the exception would drag its `__traceback__` — and the entry-referencing
        frame behind it — into the entry, recreating the reference cycle the
        done-callback exists to break (§8.3, N1).
        """
        async with self.cond:
            self.state = "failed"
            self.error = reason
            self.cond.notify_all()

    # ------------------------------------------------------------------ #
    # Reader side
    # ------------------------------------------------------------------ #

    async def read(self, *, header: bytes, max_seconds: float) -> AsyncIterator[bytes]:
        """Stream the header, then the buffer as it grows (§7.2.1).

        Lengths are snapshotted and copied out under the condition's lock
        rather than yielding views into the growing `bytearray` — a memoryview
        of a buffer being extended is invalidated by the resize. Bytes are
        yielded *outside* the lock so the writer can keep appending while the
        event loop flushes to a slow client, whose flush pacing is the natural
        backpressure.

        Ends three ways, and only one of them is quiet: `complete` returns,
        `failed` raises, and outliving `max_seconds` raises (§7.2.1's reader
        max-lifetime, which bounds how long a slow client can pin a finished
        buffer and the admission slot behind it).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_seconds
        yield header

        sent = 0
        while True:
            if loop.time() >= deadline:
                # Checked here as well as around the wait: a client that reads
                # slowly blocks on the yield below, not on the condition, so a
                # wait-only check would never fire for the exact case this
                # bound exists for.
                raise self._abort("reader max-lifetime exceeded", sent)

            async with self.cond:
                while len(self.buffer) == sent and self.state == "generating":
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise self._abort("reader max-lifetime exceeded", sent)
                    try:
                        await asyncio.wait_for(self.cond.wait(), remaining)
                    except TimeoutError:
                        raise self._abort(
                            "reader max-lifetime exceeded", sent
                        ) from None
                chunk = bytes(self.buffer[sent:])
                state, error = self.state, self.error

            if chunk:
                sent += len(chunk)
                yield chunk
                continue

            if state == "complete":
                return

            # T22: never a clean `return` here. With `0xFFFFFFFF` sizes in the
            # header, a politely-ended truncated clip is byte-identical to a
            # legitimately short verse — the aborted connection IS the failure
            # signal. See source-tts-suggestion.md §7.2.1.
            #
            # Logged first because of what happens next: the raise escapes the
            # response, so the framework's catch-all logs it a second time as
            # an unhandled ERROR (it cannot answer with a status — headers went
            # out long ago). This line is what tells an operator reading that
            # traceback that the abort was the design working, not a crash.
            raise self._abort(error or "generation failed", sent)

    def _abort(self, reason: str, sent: int) -> GenerationFailed:
        logger.warning(
            "tts reader aborting stream (by design: a truncated WAV must not "
            "end cleanly)",
            artifact_hash=self.artifact,
            reason=reason,
            bytes_sent=sent,
        )
        return GenerationFailed(self.artifact, reason)


class GenerationHeap:
    """The process's generation dict, its RAM budget, and the admission gate.

    Three collections, each answering a different question:

    * `_entries` — what is generating right now (strong references; this is what
      keeps detached tasks alive and what makes dedup work);
    * `_draining` — what has finished but still has readers reading
      (`WeakValueDictionary`, so an entry disappears the moment its last reader
      lets go);
    * `_buffered_bytes` — how much RAM the above are worth, which is the
      accounting truth. Never RSS: RSS over-reports live data after a spike
      (fragmentation, unreturned arenas) and would throttle the service
      permanently (§9.2).
    """

    def __init__(
        self,
        *,
        max_buffered_bytes: int,
        max_clip_bytes: int,
        admission_wait_seconds: float,
        retry_after_seconds: int,
    ) -> None:
        self._max_clip_bytes = max_clip_bytes
        self._admission_wait_seconds = admission_wait_seconds
        self._retry_after_seconds = retry_after_seconds

        # A count semaphore IS the byte gate once every count is worth the
        # per-clip ceiling (§9.2): concurrent generations cannot exceed the
        # budget even if every one of them runs to the provider's output cap.
        # Consciously conservative — real verse clips are a fraction of the
        # ceiling — and true byte-accounting admission was rejected as v1
        # complexity.
        self._slots = max(1, max_buffered_bytes // max_clip_bytes)
        if max_buffered_bytes < max_clip_bytes:
            logger.warning(
                "tts RAM budget is smaller than one clip; admitting one anyway",
                max_buffered_bytes=max_buffered_bytes,
                max_clip_bytes=max_clip_bytes,
            )
        self._semaphore = asyncio.Semaphore(self._slots)

        self._entries: dict[str, GenerationEntry] = {}
        self._draining: WeakValueDictionary[str, GenerationEntry] = (
            WeakValueDictionary()
        )
        self._buffered_bytes = 0
        # Guards the counter alone. A finalizer runs wherever the last
        # reference happened to drop, which is not necessarily the event loop's
        # thread (the compression tail hands the buffer to `asyncio.to_thread`),
        # so `+=` on a plain int is not safe to assume atomic here.
        self._counter_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Lookup — the first two rungs of the waterfall (§7.2)
    # ------------------------------------------------------------------ #

    def get(self, artifact: str) -> GenerationEntry | None:
        """An entry that is generating (or just finished) in this process."""
        return self._entries.get(artifact)

    def get_draining(self, artifact: str) -> GenerationEntry | None:
        """A finished entry still serving its readers, if one survives.

        Callers must consult R2 first: a new reader may attach to a draining
        entry **only while the compressed object does not exist yet** (§9.2).
        Once it does, the redirect wins — Range support, `Content-Length`,
        cacheability, and roughly a tenth of the bytes.
        """
        return self._draining.get(artifact)

    # ------------------------------------------------------------------ #
    # Admission (§9.2, T25)
    # ------------------------------------------------------------------ #

    async def admit(self, artifact: str, recipe: "TtsRecipe") -> Admission:
        """Reserve a slot for a NEW generation and register its entry.

        Gates new generations only — attaching to an existing entry, serving a
        302, and answering 404 all bypass this, because none of them allocates
        a buffer.

        Refusal is a `503` carrying `Retry-After`, raised *before* the caller
        has built any response, which is what makes §12.3's "503 + Retry-After
        before any body bytes" structural rather than a matter of ordering
        statements carefully.

        **This method is the dedup guard, and that is why the dict is checked
        three times.** Waiting for a slot is an `await`, and the caller reached
        here through two more of them (the sidecar read and the R2 HEAD) — so
        several requests for one hash can all have decided to generate. Only
        the check *after* the wait is authoritative: whoever acquires a slot
        first registers the entry synchronously, and everyone else finds it and
        attaches. Without it, five concurrent first-listens produce five
        entries, five provider calls, and five billing events for one verse —
        precisely the failure §9.2's "the dict dedups perfectly within one
        process" forbids.
        """
        existing = self._entries.get(artifact)
        if existing is not None:
            return Admission(existing, created=False)

        try:
            await asyncio.wait_for(
                self._semaphore.acquire(), self._admission_wait_seconds
            )
        except TimeoutError:
            # One last look before refusing: while this request queued, the
            # generation it wanted may have been started by another. Refusing
            # then would be a 503 for a clip that is already being synthesized.
            existing = self._entries.get(artifact)
            if existing is not None:
                return Admission(existing, created=False)
            logger.warning(
                "tts admission refused; RAM budget saturated",
                artifact_hash=artifact,
                buffered_bytes=self.buffered_bytes,
                slots=self._slots,
            )
            raise ServiceUnavailableException(
                message=(
                    "The audio generation buffer is full. Retry in "
                    f"{self._retry_after_seconds} seconds."
                ),
                code=ErrorCode.TTS_BUSY,
                retry_after=self._retry_after_seconds,
            ) from None

        existing = self._entries.get(artifact)
        if existing is not None:
            # Someone else won the race while this request waited. Hand the
            # slot straight back — holding it would shrink the budget by one
            # for as long as the winner's clip lasts.
            self._semaphore.release()
            return Admission(existing, created=False)

        buffer = GenerationBuffer()
        with self._counter_lock:
            self._buffered_bytes += self._max_clip_bytes

        # Registered against the buffer, not the entry: the buffer is the
        # memory, and this is what ties the slot's life to the bytes' life. The
        # callback takes only plain values — capturing the entry or the buffer
        # here would keep alive the very thing whose death it waits for.
        weakref.finalize(
            buffer,
            self._release,
            artifact,
            self._max_clip_bytes,
            asyncio.get_running_loop(),
        )

        entry = GenerationEntry(artifact=artifact, recipe=recipe, buffer=buffer)
        self._entries[artifact] = entry
        return Admission(entry, created=True)

    def _release(self, artifact: str, nbytes: int, loop: asyncio.AbstractEventLoop):
        """Give back one slot's bytes, called by the buffer's finalizer."""
        with self._counter_lock:
            self._buffered_bytes -= nbytes
        try:
            # Scheduled rather than called: `Semaphore.release()` touches the
            # loop's waiter futures, and a finalizer can fire on a worker
            # thread (see `_counter_lock`). `call_soon_threadsafe` is correct
            # from the loop's own thread too, at the cost of one tick.
            loop.call_soon_threadsafe(self._semaphore.release)
        except RuntimeError:
            # The loop is closed — the process is going away (or a test's loop
            # ended before this buffer was collected). The slot dies with it.
            logger.debug(
                "tts admission slot released after loop close",
                artifact_hash=artifact,
            )

    # ------------------------------------------------------------------ #
    # Lifecycle transitions
    # ------------------------------------------------------------------ #

    def drain(self, entry: GenerationEntry) -> None:
        """Move a finished entry to the draining set (§9.2).

        Attached readers keep it alive by holding it; when the last one lets
        go, the entry and its buffer are collected and the finalizer above
        returns the slot. An entry with no readers left simply vanishes here,
        which is the correct amount of work to do about it.
        """
        self._forget(entry)
        self._draining[entry.artifact] = entry

    def discard(self, entry: GenerationEntry) -> None:
        """Drop a failed entry so a client's retry re-enters through admission.

        There is no server-side retry (§8.3): a second attempt's bytes could
        never be spliced into streams that already delivered part of the first
        (the provider is nondeterministic), and retrying inside the task would
        hold an admission slot hostage for the duration of provider trouble.
        """
        self._forget(entry)

    def _forget(self, entry: GenerationEntry) -> None:
        """Remove `entry` from the primary dict, if it is still the current one.

        The identity check matters: after a failure the client retries, and a
        *new* entry for the same hash may already be registered — removing by
        key alone would evict a healthy generation that other readers are
        listening to.
        """
        if self._entries.get(entry.artifact) is entry:
            del self._entries[entry.artifact]

    # ------------------------------------------------------------------ #
    # Observability (also what the admission tests assert against)
    # ------------------------------------------------------------------ #

    @property
    def buffered_bytes(self) -> int:
        """Bytes currently reserved by live buffers — the accounting truth."""
        with self._counter_lock:
            return self._buffered_bytes

    @property
    def slots(self) -> int:
        """Worst-case concurrent generations, ⌊budget / per-clip ceiling⌋."""
        return self._slots

    @property
    def max_clip_bytes(self) -> int:
        """Per-clip ceiling: one slot's reservation and the per-append tripwire."""
        return self._max_clip_bytes
