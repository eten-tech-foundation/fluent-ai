"""
Shared fakes for the Source-TTS tests.

No test in this suite may need real R2 credentials or a real provider key: the
dev bucket costs nothing but a network round-trip is a flake, and a real
provider call costs money. So the seams are faked at their narrowest points —
the botocore client and the provider protocol — which keeps our own wrapper
logic (conditional-PUT conflict handling, key layout, error mapping) under
test rather than mocked away.
"""

import hashlib
import io
from typing import Any

from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.services.tts.provider import TtsProviderRequest


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
        "tts_max_text_length": 20_000,
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
            "ResponseMetadata": {"HTTPStatusCode": status_code},
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
        self.fail_next_put_with: ClientError | None = None

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
    """Counts synthesis attempts so "generate never synthesizes" is provable.

    `ignored_fields` defaults to Gemini's real declaration so the common case
    under test is the shipped one; tests that care about a provider for which
    `lang_code` matters pass an empty set.
    """

    def __init__(self, ignored_fields: frozenset[str] | None = None) -> None:
        self.ignored_fields = (
            frozenset({"lang_code"}) if ignored_fields is None else ignored_fields
        )
        self.synthesize_calls: list[TtsProviderRequest] = []

    def non_byte_affecting_fields(self) -> frozenset[str]:
        return self.ignored_fields

    def synthesize_stream(self, request: TtsProviderRequest):
        self.synthesize_calls.append(request)
        raise AssertionError(
            "synthesize_stream must never be reached from generate (T8)"
        )
