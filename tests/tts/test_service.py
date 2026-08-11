"""
tests/tts/test_service.py — service-level rules that no endpoint test can see.

Mostly about the receipt sidecar (§9.3), whose whole design is negative: it is
not a commit marker, not sensitive, not a ledger, and never read by anything
load-bearing. Those properties only stay true if something asserts them.
"""

import json

import pytest
from botocore.exceptions import ClientError

from app.schemas.tts import TtsGenerateRequest
from app.services.tts.artifacts import TtsArtifactStore
from app.services.tts.recipe import build_recipe
from app.services.tts.service import TtsService
from tests.tts.fakes import FakeS3Client, FakeTtsProvider, tts_settings


HASH = "b" * 64


@pytest.fixture
def r2() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def service(r2) -> TtsService:
    settings = tts_settings()
    store = TtsArtifactStore(
        client=r2,  # type: ignore[arg-type] - fake with the same call surface
        bucket="fluent-tts-test",
        prefix=settings.tts_r2_prefix,
    )
    return TtsService(settings=settings, store=store, provider=FakeTtsProvider())


def a_recipe(**overrides):
    payload = {"text": "In the beginning", **overrides}
    return build_recipe(
        TtsGenerateRequest(**payload),
        settings=tts_settings(),
        provider=FakeTtsProvider(),
    )


class TestReceipt:
    @pytest.mark.asyncio
    async def test_receipt_carries_metadata_only(self, service, r2):
        await service.write_receipt(
            HASH, recipe=a_recipe(), duration_ms=4380, size_bytes=31240
        )

        stored = r2.objects[f"tts/receipts/{HASH}.json"]
        body = json.loads(stored["body"])
        assert body["recipe_version"] == "v1"
        assert body["model"] == "test-tts-model"
        assert body["voice"] == "Kore"
        assert body["format"] == "ogg-opus"
        assert body["content_type"] == "audio/ogg"
        assert body["duration_ms"] == 4380
        assert body["size_bytes"] == 31240
        assert body["created_at"]

    @pytest.mark.asyncio
    async def test_receipt_contains_no_text_and_no_user_identity(self, service, r2):
        """It is publicly fetchable from the bucket domain, so it must not be a
        second copy of the content or say who asked for it."""
        await service.write_receipt(
            HASH, recipe=a_recipe(), duration_ms=None, size_bytes=1
        )
        raw = r2.objects[f"tts/receipts/{HASH}.json"]["body"].decode("utf-8")
        assert "In the beginning" not in raw
        body = json.loads(raw)
        assert not any(
            key in body for key in ("text", "user_id", "owner_user_id", "project_id")
        )

    @pytest.mark.asyncio
    async def test_receipt_write_failure_is_swallowed(self, service, r2):
        """A cosmetic write must never fail a request: the audio object's
        presence is self-certifying, so a missing receipt is a non-event."""
        r2.fail_next_put_with = ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "no"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )
        await service.write_receipt(
            HASH, recipe=a_recipe(), duration_ms=None, size_bytes=1
        )  # must not raise
        assert r2.objects == {}

    @pytest.mark.asyncio
    async def test_receipt_is_written_unconditionally(self, service, r2):
        """Unlike sidecars and audio, a receipt may be rewritten: it is not an
        immutable artifact and a conflict here would be pure noise."""
        await service.write_receipt(
            HASH, recipe=a_recipe(), duration_ms=None, size_bytes=1
        )
        assert r2.put_calls[0]["if_none_match"] is None


class TestAudioKey:
    def test_format_selects_the_object_extension(self, service):
        assert service.audio_key(HASH, "ogg-opus") == f"tts/audio/{HASH}.ogg"
        assert service.audio_key(HASH, "mp3") == f"tts/audio/{HASH}.mp3"

    def test_opus_lives_in_an_ogg_container(self, service):
        """The format name describes the codec, the extension the container —
        conflating them is how a `.opus` key nothing serves gets created."""
        assert service.audio_key(HASH, "ogg-opus").endswith(".ogg")
