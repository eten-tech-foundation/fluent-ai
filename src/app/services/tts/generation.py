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


SHUTDOWN_GRACE_SECONDS = 5.0
"""How long shutdown waits for cancelled generations to finish tearing down.

A **constant, not a setting**, because there is no deployment in which turning
it would be the right move — it is bounded on both sides by things nobody
configures here:

* below, by what the teardown actually does — close the provider's stream, mark
  the entry failed, discard it. All of that is in-memory and takes a loop tick,
  except the stream close, which is one network teardown;
* above, by the platform's own kill timeout, since a grace longer than that is
  spent in a process the orchestrator is about to `SIGKILL` anyway. The smallest
  common one is Docker's default 10 s (Kubernetes' is 30 s).

Five seconds sits inside the smaller of those with room to spare. If it is ever
exceeded, the log line says so by name — that is a stuck provider stream, and it
is worth reading rather than worth a bigger number.

**This grace is third in line, which is why tuning it buys so little** (traced
in uvicorn's `Server.shutdown`, reviewed with the operator 2026-08-16). On
SIGTERM uvicorn stops accepting, asks live connections to close, and then waits
for in-flight responses — bounded by `--timeout-graceful-shutdown`, which our
Dockerfile sets to **30 s** — and only *afterwards* runs the lifespan shutdown
that calls into here. A listener streaming a clip is one of those in-flight
responses, so a deploy caught mid-generation spends up to 30 s in that drain
**with the generation still running and still billing**, because the generation
task is detached (`asyncio.create_task`, not one of uvicorn's) and nothing has
cancelled it yet. Worst-case shutdown is therefore ~35 s, of which this constant
is the last five. Two consequences worth knowing before changing anything here:
the number that dominates deploy-time cost is the 30 s drain, not this one; and
under Docker's default 10 s stop grace (or Kubernetes' default 30 s) the
`SIGKILL` can land *before* this code ever runs. Confirm the deployment
platform's effective kill timeout before changing either shutdown value.
"""


class GenerationBuffer(bytearray):
    """A `bytearray` that can be weak-referenced.

    §9.2 prescribes `weakref.finalize(buffer, release, nbytes)` so an admission
    slot is released exactly when the memory is, by refcount, rather than
    whenever the cyclic collector next runs. A plain `bytearray` cannot be the
    target of a weak reference at all (`TypeError` at `weakref.ref`), and a
    subclass is the smallest thing that can: it adds a `__weakref__` slot, 32
    bytes per buffer, and keeps every `bytearray` operation the writer and the
    readers use.

    Do not give this class `__slots__` — an empty-bodied subclass is exactly
    the shape someone "tidies up" that way, and it suppresses `__weakref__`
    again, which takes `weakref.finalize` back to the same `TypeError` a plain
    `bytearray` raises. That failure is loud and immediate (the first
    generation dies), not a quiet drift back to GC-timed accounting.
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
        # budget even if every one of them runs to the ceiling. The guarantee
        # is arithmetic rather than probabilistic, which is why admission never
        # has to measure anything — and why the ceiling and the budget are not
        # independent knobs.
        #
        # ------------------------------------------------------------------ #
        # If you outgrow this, here is the next design — deliberately NOT built
        # (operator decision, 2026-08-13: ship the simple gate, revisit if it
        # bites). Two symptoms say it is time: 503s while the process is
        # obviously not short of memory, or generations larger than a verse
        # becoming a legitimate use case.
        #
        # The cost of a count gate is that every reservation is worst-case, so
        # a five-second verse holds a slot sized for a three-minute one, and a
        # stalled reader pins that whole slot until its buffer dies. Replace it
        # with a byte budget:
        #
        #   * one integer of outstanding reservations, plus a set of waiting
        #     `asyncio.Event`s;
        #   * admit when `outstanding + want <= budget`, taking the bytes in the
        #     SAME synchronous step as the check;
        #   * on any release (or shrink), subtract and `set()` every waiter;
        #     each waiter re-checks in a loop.
        #
        # Three properties make it right by construction, and all three are
        # things a reviewer can check by reading rather than by reasoning about
        # timing:
        #
        #   1. every mutation is synchronous and on the event loop, so no two
        #      interleave and no lock is needed (the one off-loop caller, the
        #      buffer's finalizer, already trampolines through
        #      `call_soon_threadsafe` — see `_release`);
        #   2. no lost wakeups: the failed check and the waiter's registration
        #      are separated by no `await`, so any later release sees it;
        #   3. spurious wakeups are harmless, because the waiter re-checks.
        #
        # Starvation of a large reservation is possible and is bounded by the
        # existing admission timeout — it degrades to a 503 + Retry-After, which
        # is a shipped failure mode, so no fairness queue is required.
        #
        # That unlocks two things this gate cannot express: reservations sized
        # per clip (estimated from the text — ~4,000 bytes of PCM per character,
        # see `config.py`'s sizing block), and shrinking a reservation to the
        # clip's true size once the stream completes, so a stalled reader pins
        # what it actually holds. The one hazard to respect is reference
        # topology, not arithmetic: a shrinkable reservation must live in a
        # holder that the buffer cannot reach, or the finalizer that releases it
        # will never fire (N1, and the reason `_release` takes plain values).
        # ------------------------------------------------------------------ #
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
        try:
            # Both accounting and semaphore release run together on the loop.
            # A finalizer can fire during GC on this thread or on a worker
            # thread, so it must never acquire a lock or mutate the counter.
            loop.call_soon_threadsafe(self._give_back, nbytes)
        except RuntimeError:
            # The loop is closed — the process is going away (or a test's loop
            # ended before this buffer was collected). The slot dies with it.
            logger.debug(
                "tts admission slot released after loop close",
                artifact_hash=artifact,
            )

    def _give_back(self, nbytes: int) -> None:
        self._buffered_bytes -= nbytes
        self._semaphore.release()

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

    async def cancel_all(self, *, grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> int:
        """Cancel every in-flight generation and let each one's teardown run.

        §8.3's shutdown half. Cancelling **is** the design here — there is
        deliberately no drain-and-finish: a clip finished after the listeners'
        connections have died costs provider money to produce for nobody, and
        the request sidecar on R2 means the restarted process (or any other
        replica) regenerates on the next request. Nothing durable is lost.

        What the bounded wait buys is that the *receiving* half actually runs.
        `CancelledError` is what wakes readers so they abort instead of ending
        politely, marks the entry failed, drops it out of the dict and lets its
        buffer (and the admission slot behind it) go. Cancel without awaiting
        and none of that happens: the loop closes on tasks suspended mid-write
        and asyncio logs `Task was destroyed but it is pending!` on every deploy
        that catches a generation in flight.

        Returns how many tasks were cancelled, which is what the shutdown log
        line and the tests read.
        """
        # Snapshot first: each task's teardown mutates `_entries` (via
        # `discard`) and clears its own `entry.task` in the done-callback, so
        # iterating the live dict here would be iterating what we are ending.
        tasks = [
            entry.task
            for entry in list(self._entries.values())
            if entry.task is not None
        ]
        if not tasks:
            return 0

        logger.info(
            "tts shutdown cancelling in-flight generations",
            count=len(tasks),
            buffered_bytes=self.buffered_bytes,
        )
        for task in tasks:
            task.cancel()

        _, pending = await asyncio.wait(tasks, timeout=grace_seconds)
        if pending:
            # Not fatal, and not retried: the process is going away regardless.
            # Named because the only way to get here is a provider stream whose
            # close is stuck, which is a fact about the provider worth having.
            logger.warning(
                "tts generations still pending after the shutdown grace period",
                count=len(pending),
                grace_seconds=grace_seconds,
                tasks=sorted(task.get_name() for task in pending),
            )
        return len(tasks)

    # ------------------------------------------------------------------ #
    # Observability (also what the admission tests assert against)
    # ------------------------------------------------------------------ #

    @property
    def buffered_bytes(self) -> int:
        """Bytes currently reserved by live buffers — the accounting truth."""
        return self._buffered_bytes

    @property
    def slots(self) -> int:
        """Worst-case concurrent generations, ⌊budget / per-clip ceiling⌋."""
        return self._slots

    @property
    def max_clip_bytes(self) -> int:
        """Per-clip ceiling: one slot's reservation and the per-append tripwire."""
        return self._max_clip_bytes
