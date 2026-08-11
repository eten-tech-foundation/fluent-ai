"""
tests/tts/test_artifacts.py — the R2 artifact store (source-tts proposal §9.3).

Faked at the botocore client, so the wrapper's own rules stay under test: the
key layout, "a conditional-PUT conflict is success", absence-is-not-an-error on
HEAD/GET, and the refusal to boot-fail when TTS is unconfigured.
"""

import json

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException, ServiceUnavailableException
from app.services.tts.artifacts import (
    JSON_CONTENT_TYPE,
    TtsArtifactStore,
    build_artifact_store,
    serialize_json_body,
)
from tests.tts.fakes import FakeS3Client, tts_settings


@pytest.fixture
def client() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def store(client: FakeS3Client) -> TtsArtifactStore:
    return TtsArtifactStore(client=client, bucket="fluent-tts-test", prefix="tts/")


HASH = "a" * 64


class TestKeyLayout:
    def test_the_three_prefixes_live_under_the_configured_prefix(self, store):
        assert store.request_key(HASH) == f"tts/requests/{HASH}.json"
        assert store.audio_key(HASH, "ogg") == f"tts/audio/{HASH}.ogg"
        assert store.receipt_key(HASH) == f"tts/receipts/{HASH}.json"

    def test_an_empty_prefix_yields_bare_keys(self, client):
        store = TtsArtifactStore(client=client, bucket="b", prefix="")
        assert store.request_key(HASH) == f"requests/{HASH}.json"

    def test_prefix_is_normalized_by_settings_not_by_callers(self):
        """One canonical shape, so keys cannot differ by a stray slash and
        create a second, parallel artifact namespace."""
        assert tts_settings(tts_r2_prefix="tts").tts_r2_prefix == "tts/"
        assert tts_settings(tts_r2_prefix="/tts").tts_r2_prefix == "tts/"
        assert tts_settings(tts_r2_prefix="").tts_r2_prefix == ""


class TestConditionalPut:
    @pytest.mark.asyncio
    async def test_first_write_wins_and_reports_that_it_wrote(self, store, client):
        written = await store.put_if_absent(
            "tts/requests/x.json", b"{}", content_type=JSON_CONTENT_TYPE
        )
        assert written is True
        assert client.put_calls[0]["if_none_match"] == "*"
        assert client.put_calls[0]["content_type"] == JSON_CONTENT_TYPE

    @pytest.mark.asyncio
    async def test_a_conflict_is_success_not_an_error(self, store, client):
        """First-writer-wins: every writer is storing the same artifact for the
        same hash, so a 412 means "already done", not "failed"."""
        await store.put_if_absent("k", b"first", content_type=JSON_CONTENT_TYPE)
        written = await store.put_if_absent(
            "k", b"second", content_type=JSON_CONTENT_TYPE
        )
        assert written is False
        # The loser must not have overwritten the winner: objects are immutable.
        assert client.objects["k"]["body"] == b"first"

    @pytest.mark.asyncio
    async def test_other_client_errors_become_a_storage_error(self, store, client):
        client.fail_next_put_with = ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "no"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )
        with pytest.raises(ExternalServiceException) as caught:
            await store.put_if_absent("k", b"{}", content_type=JSON_CONTENT_TYPE)
        assert caught.value.code == ErrorCode.TTS_STORAGE_ERROR

    @pytest.mark.asyncio
    async def test_transport_failures_become_a_storage_error(self, store, client):
        client.fail_next_put_with = EndpointConnectionError(  # type: ignore[assignment]
            endpoint_url="https://example.invalid"
        )
        with pytest.raises(ExternalServiceException):
            await store.put_if_absent("k", b"{}", content_type=JSON_CONTENT_TYPE)

    @pytest.mark.asyncio
    async def test_unconditional_put_is_available_for_receipts(self, store, client):
        await store.put("k", b"once", content_type=JSON_CONTENT_TYPE)
        await store.put("k", b"twice", content_type=JSON_CONTENT_TYPE)
        assert client.objects["k"]["body"] == b"twice"
        assert [call["if_none_match"] for call in client.put_calls] == [None, None]


class TestReads:
    @pytest.mark.asyncio
    async def test_head_returns_none_when_absent(self, store):
        assert await store.head("missing") is None

    @pytest.mark.asyncio
    async def test_head_reports_size_etag_and_content_type(self, store):
        await store.put("k", b"12345", content_type="audio/ogg")
        head = await store.head("k")
        assert head is not None
        assert head.size_bytes == 5
        assert head.content_type == "audio/ogg"
        assert head.etag

    @pytest.mark.asyncio
    async def test_get_bytes_returns_none_when_absent(self, store):
        assert await store.get_bytes("missing") is None

    @pytest.mark.asyncio
    async def test_get_json_round_trips_a_sidecar(self, store):
        body = {"recipe_version": "v1", "text": "hello", "lang_code": None}
        await store.put_if_absent(
            "k", serialize_json_body(body), content_type=JSON_CONTENT_TYPE
        )
        assert await store.get_json("k") == body

    @pytest.mark.asyncio
    async def test_a_corrupt_sidecar_is_an_error_not_a_silent_absence(self, store):
        """Reporting "absent" would send the serving waterfall to its 404 rung
        and tell the client to re-authorize an artifact that already is."""
        await store.put("k", b"not json", content_type=JSON_CONTENT_TYPE)
        with pytest.raises(ExternalServiceException) as caught:
            await store.get_json("k")
        assert caught.value.code == ErrorCode.TTS_STORAGE_ERROR

    @pytest.mark.asyncio
    async def test_a_json_scalar_body_is_also_rejected(self, store):
        await store.put("k", b"42", content_type=JSON_CONTENT_TYPE)
        with pytest.raises(ExternalServiceException):
            await store.get_json("k")


class TestSerialization:
    def test_bodies_are_deterministic_regardless_of_key_order(self):
        """Byte-identical sidecars on every replica are what let a conditional
        PUT conflict be treated as success without comparing contents."""
        assert serialize_json_body({"a": 1, "b": 2}) == serialize_json_body(
            {"b": 2, "a": 1}
        )

    def test_non_ascii_text_is_stored_as_utf8_not_escapes(self):
        body = serialize_json_body({"text": "ἐν ἀρχῇ"})
        assert json.loads(body)["text"] == "ἐν ἀρχῇ"
        assert "ἐν" in body.decode("utf-8")


class TestConstruction:
    def test_unconfigured_storage_fails_cleanly_at_request_time(self):
        """The service must boot without TTS configuration — only TTS routes
        may fail, and they must fail as 503 with a nameable code."""
        settings = tts_settings(r2_account_id=None)
        with pytest.raises(ServiceUnavailableException) as caught:
            build_artifact_store(settings)
        assert caught.value.status_code == 503
        assert caught.value.code == ErrorCode.TTS_STORAGE_NOT_CONFIGURED

    def test_a_missing_hash_secret_alone_blocks_construction(self):
        """An artifact name computed without the secret is a bare hash of
        public text, so a blank secret is a misconfiguration, not a default."""
        with pytest.raises(ServiceUnavailableException):
            build_artifact_store(tts_settings(tts_hash_secret=None))

    def test_endpoint_is_derived_from_account_and_jurisdiction(self):
        assert (
            tts_settings(r2_account_id="acct", r2_jurisdiction="eu").r2_endpoint_url
            == "https://acct.eu.r2.cloudflarestorage.com"
        )
        assert (
            tts_settings(
                r2_account_id="acct", r2_jurisdiction="default"
            ).r2_endpoint_url
            == "https://acct.r2.cloudflarestorage.com"
        )

    def test_a_configured_deployment_builds_a_real_client(self):
        """No network happens here — boto3 client construction is local — but
        it proves the settings we pass are ones botocore accepts."""
        store = build_artifact_store(tts_settings())
        assert store.request_key(HASH).startswith("tts/requests/")
