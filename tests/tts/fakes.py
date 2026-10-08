"""
Shared fakes for the Source-TTS tests.

No test in this suite may need real R2 credentials or a real provider key: the
dev bucket costs nothing but a network round-trip is a flake, and a real
provider call costs money. So the seams are faked at their narrowest points —
the botocore client and the provider protocol — which keeps our own wrapper
logic (conditional-PUT conflict handling, key layout, error mapping) under
test rather than mocked away.
"""

import asyncio
import hashlib
import io
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.config import MAX_TEXT_CHARS, Settings, get_settings
from app.services.tts.compression import CompressedClip
from app.services.tts.provider import PcmFormat, TtsProviderRequest


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def tts_settings(**overrides: Any) -> Settings:
    """Real Settings with a complete, fake TTS configuration applied.

    Derived from the process settings rather than constructed from scratch, so
    the required non-TTS fields (database URL, api key) keep whatever the
    environment supplies and this helper stays about TTS only.

    Re-**validated** deliberately: `model_copy(update=...)` assigns fields
    without running validators, so a helper built that way would hand tests a
    `tts_r2_prefix` that production would never produce (`'tts'` instead of
    `'tts/'`) and quietly hide the normalizer. `model_validate` runs the same
    code path a real boot does.
    """
    base = {
        "r2_account_id": "fake-account",
        "r2_access_key_id": "fake-key-id",
        "r2_secret_access_key": "fake-secret",
        "r2_jurisdiction": "eu",
        "r2_tts_bucket": "fluent-tts-test",
        "tts_r2_prefix": "tts/",
        "tts_public_audio_base_url": "https://tts.example.test",
        "tts_hash_secret": "test-hash-secret",
        "tts_model": "test-tts-model",
        "tts_voice": "Kore",
        "tts_default_format": "ogg-opus",
        # Pinned to the shipped default rather than a number of its own: a
        # developer's .env must not change what the length tests exercise.
        "tts_max_text_length": MAX_TEXT_CHARS,
    }
    base.update(overrides)
    return Settings.model_validate({**get_settings().model_dump(), **base})


# --------------------------------------------------------------------------- #
# Fake R2 (botocore S3 client surface)
# --------------------------------------------------------------------------- #


def _client_error(code: str, status_code: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {
                "HTTPStatusCode": status_code,
                "HTTPHeaders": {},
                "HostId": "",
                "RequestId": "",
                "RetryAttempts": 0,
            },
        },
        operation,
    )


class FakeS3Client:
    """In-memory object store with the four behaviours the design relies on.

    The important one is `IfNoneMatch="*"`: R2 really does enforce it, answering
    `412 PreconditionFailed` when the key exists (verified against the real dev
    bucket on 2026-08-11). The whole "conflict means success" rule rests on
    that, so the fake reproduces it exactly rather than approximating it with a
    silent overwrite.
    """

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []
        self.fail_next_put_with: ClientError | BotoCoreError | None = None

    # -- writes ---------------------------------------------------------- #

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str | None = None,
        IfNoneMatch: str | None = None,
    ) -> dict[str, Any]:
        self.put_calls.append(
            {
                "bucket": Bucket,
                "key": Key,
                "body": Body,
                "content_type": ContentType,
                "if_none_match": IfNoneMatch,
            }
        )
        if self.fail_next_put_with is not None:
            error, self.fail_next_put_with = self.fail_next_put_with, None
            raise error
        if IfNoneMatch == "*" and Key in self.objects:
            raise _client_error("PreconditionFailed", 412, "PutObject")
        self.objects[Key] = {"body": Body, "content_type": ContentType}
        return {"ETag": f'"{hashlib.md5(Body).hexdigest()}"'}

    # -- reads ----------------------------------------------------------- #

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.head_calls.append(Key)
        stored = self.objects.get(Key)
        if stored is None:
            raise _client_error("404", 404, "HeadObject")
        return {
            "ContentLength": len(stored["body"]),
            "ETag": f'"{hashlib.md5(stored["body"]).hexdigest()}"',
            "ContentType": stored["content_type"],
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.get_calls.append(Key)
        stored = self.objects.get(Key)
        if stored is None:
            raise _client_error("NoSuchKey", 404, "GetObject")
        return {"Body": io.BytesIO(stored["body"])}

    # -- assertions helpers ---------------------------------------------- #

    def conditional_puts(self, key: str) -> list[dict[str, Any]]:
        return [
            call
            for call in self.put_calls
            if call["key"] == key and call["if_none_match"] == "*"
        ]


# --------------------------------------------------------------------------- #
# Fake provider
# --------------------------------------------------------------------------- #


class FakeTtsProvider:
    """One fake, two jobs — and the default job is refusing to synthesize.

    With no `chunks`, `synthesize_stream` raises: that is what makes "generate
    never synthesizes" (T8) provable rather than assumed. Hand it `chunks` and
    it becomes a scriptable stream for the serving waterfall:

    * `chunks` — the PCM it yields, one append per chunk;
    * `fail_after` — raise once that many chunks have been yielded,
      which is the mid-stream provider error §7.2.1's abort path exists for;
    * `paced` — hold before every chunk until `release()` is called, so a test
      can observe a reader receiving bytes *while* the buffer is still growing
      instead of racing a completed generation.

    `ignored_fields` defaults to Gemini's real declaration so the common case
    under test is the shipped one; tests that care about a provider for which
    `lang_code` matters pass an empty set.
    """

    def __init__(
        self,
        ignored_fields: frozenset[str] | None = None,
        *,
        chunks: list[bytes] | None = None,
        fail_after: int | None = None,
        failure_type: type[Exception] = RuntimeError,
        failure_message: str = "fake provider failed mid-stream",
        paced: bool = False,
        pcm: PcmFormat | None = None,
    ) -> None:
        self.ignored_fields = (
            frozenset({"lang_code"}) if ignored_fields is None else ignored_fields
        )
        self.synthesize_calls: list[TtsProviderRequest] = []
        self.closed_streams = 0
        self.chunks = chunks
        self.fail_after = fail_after
        # A *type* and a message, not a prepared exception instance: an
        # exception that has been raised carries a `__traceback__`, and holding
        # one on the fake would keep the failed generation's frames — and so
        # its entry and its whole buffer — alive for the rest of the test.
        # (Found the hard way: an accounting assertion failed because the fake,
        # not the service, was pinning 30 MiB.)
        self.failure_type = failure_type
        self.failure_message = failure_message
        self.paced = paced
        self.pcm = pcm or PcmFormat(
            sample_rate_hz=24000, channels=1, bits_per_sample=16
        )
        self._resume = asyncio.Event()
        self._pending = 0

    def non_byte_affecting_fields(self) -> frozenset[str]:
        return self.ignored_fields

    def pcm_format(self) -> PcmFormat:
        return self.pcm

    def release(self, count: int = 1) -> None:
        """Let the paced stream emit its next chunk(s)."""
        self._pending += count
        self._resume.set()

    async def synthesize_stream(self, request: TtsProviderRequest):
        self.synthesize_calls.append(request)
        try:
            if self.chunks is None:
                raise AssertionError(
                    "synthesize_stream must never be reached from generate (T8)"
                )
            for index, chunk in enumerate(self.chunks):
                if index == self.fail_after:
                    raise self.failure_type(self.failure_message)
                if self.paced:
                    await self._await_release()
                yield chunk
            if len(self.chunks) == self.fail_after:
                raise self.failure_type(self.failure_message)
        finally:
            self.closed_streams += 1

    async def _await_release(self) -> None:
        while self._pending <= 0:
            self._resume.clear()
            await self._resume.wait()
        self._pending -= 1


# --------------------------------------------------------------------------- #
# Fake compressor (the ffmpeg seam)
# --------------------------------------------------------------------------- #


class FakeCompressor:
    """The compression tail's encoder, without a subprocess.

    Every service-level test gets one of these, and that is deliberate: the
    tail runs on *every* completed generation, so a suite that used the real
    `FfmpegCompressor` would spawn an ffmpeg per finished clip — slow, and it
    would make unrelated waterfall tests depend on a binary being installed.
    The real encoder is exercised directly in `test_compression.py`.

    `calls` is what the "HEAD-present skips the encode" test asserts against:
    the claim is that ffmpeg is never *reached*, and an empty list is the only
    honest way to show it.
    """

    def __init__(
        self,
        *,
        data: bytes = b"OggS-fake-compressed",
        duration_ms: int | None = 1500,
        content_type: str = "audio/ogg",
        failure_type: type[Exception] | None = None,
        failure_message: str = "fake compressor failed",
    ) -> None:
        self.data = data
        self.duration_ms = duration_ms
        self.content_type = content_type
        # A type and a message, never a prepared exception instance — the same
        # rule as `FakeTtsProvider`, and for the same reason, re-learned here:
        # a raised exception's `__traceback__` chains the tail's frames, which
        # hold `entry` as a local, so a fake storing one keeps the whole entry
        # (and its buffer, and its admission slot) alive for the rest of the
        # test. It reads as a leak in the service and is not one.
        self.failure_type = failure_type
        self.failure_message = failure_message
        self.calls: list[tuple[int, PcmFormat, str]] = []

    async def compress(
        self, pcm: bytes, *, pcm_format: PcmFormat, target_format: str
    ) -> CompressedClip:
        # The PCM's *length* rather than the bytes: holding the buffer's
        # contents here would pin the very allocation the accounting tests
        # measure (§9.2 is refcount-exact).
        self.calls.append((len(pcm), pcm_format, target_format))
        if self.failure_type is not None:
            raise self.failure_type(self.failure_message)
        return CompressedClip(
            data=self.data,
            duration_ms=self.duration_ms,
            content_type=self.content_type,
        )
