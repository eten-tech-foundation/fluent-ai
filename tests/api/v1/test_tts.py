"""
tests/api/v1/test_tts.py — POST /tts/generate (source-tts proposal §7.1).

Everything below the HTTP layer is real: validation, recipe resolution, the
HMAC, and the sidecar write all run. Only the botocore client and the provider
are fakes, so what these tests prove is the endpoint's actual behaviour rather
than a mock's.
"""

import re
import uuid
from datetime import datetime, timezone

import pytest

from app.dependencies import get_tts_service, require_api_key
from app.errors.codes import ErrorCode
from app.main import app
from app.models.api_key import ApiKey
from app.schemas.tts import TtsGenerateRequest
from app.services.tts.artifacts import TtsArtifactStore, build_artifact_store
from app.services.tts.recipe import artifact_hash, build_recipe
from app.services.tts.service import TtsService
from tests.tts.fakes import (
    FakeCompressor,
    FakeS3Client,
    FakeTtsProvider,
    tts_settings,
)


ENDPOINT = "/tts/generate"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_api_key():
    record = ApiKey()
    record.id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    record.key_hash = "irrelevant"
    record.name = "test-key"
    record.permissions = []
    record.is_active = True
    record.owner_user_id = 42
    record.owner_org_id = None
    record.created_at = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    record.expires_at = None
    return record


@pytest.fixture
def r2() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def provider() -> FakeTtsProvider:
    return FakeTtsProvider()


@pytest.fixture
def settings():
    return tts_settings()


@pytest.fixture
def service(r2, provider, settings) -> TtsService:
    store = TtsArtifactStore(
        client=r2,  # type: ignore[arg-type] - fake with the same call surface
        bucket=settings.r2_tts_bucket or "bucket",
        prefix=settings.tts_r2_prefix,
    )
    return TtsService(
        settings=settings,
        store=store,
        provider=provider,
        compressor=FakeCompressor(),
    )


@pytest.fixture
def authed_client(client, fake_api_key, service):
    app.dependency_overrides[require_api_key] = lambda: fake_api_key
    app.dependency_overrides[get_tts_service] = lambda: service
    yield client
    app.dependency_overrides.pop(require_api_key, None)
    app.dependency_overrides.pop(get_tts_service, None)


def expected_hash(payload: dict, settings, provider) -> str:
    recipe = build_recipe(
        TtsGenerateRequest(**payload), settings=settings, provider=provider
    )
    return artifact_hash(recipe, secret=settings.tts_hash_secret)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGenerateSuccess:
    def test_returns_a_sibling_relative_audio_url(
        self, authed_client, settings, provider
    ):
        payload = {"text": "In the beginning", "lang_code": "eng"}
        response = authed_client.post(ENDPOINT, json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        digest = expected_hash(payload, settings, provider)
        assert body["audio_url"] == f"audio/{digest}.wav"

        # Sibling-relative means exactly this: no scheme and no leading slash,
        # so the caller resolves it against the URL it actually called (§7.1).
        assert "://" not in body["audio_url"]
        assert not body["audio_url"].startswith("/")

    def test_response_carries_nothing_but_audio_url(self, authed_client):
        """No duration field (T22) and no stray camelCase key: fluent-api
        forwards this body unmodified, so whatever ships here reaches the
        browser verbatim."""
        body = authed_client.post(ENDPOINT, json={"text": "hello"}).json()
        assert set(body) == {"audio_url"}
        assert "duration_ms" not in body
        assert "durationMs" not in body
        assert "audioUrl" not in body

    def test_hash_matches_what_fluent_api_will_accept_in_a_path(self, authed_client):
        """fluent-api validates `{hash}.{ext}` as [a-f0-9]{16,128}; a hash it
        rejects would make every audio fetch 400 while generate looked fine."""
        body = authed_client.post(ENDPOINT, json={"text": "hello"}).json()
        digest = body["audio_url"].removeprefix("audio/").removesuffix(".wav")
        assert re.fullmatch(r"[a-f0-9]{16,128}", digest)

    def test_writes_the_request_sidecar_with_a_conditional_put(
        self, authed_client, r2, settings, provider
    ):
        payload = {"text": "In the beginning", "voice": "Puck", "format": "mp3"}
        authed_client.post(ENDPOINT, json=payload)

        digest = expected_hash(payload, settings, provider)
        key = f"tts/requests/{digest}.json"
        assert len(r2.conditional_puts(key)) == 1
        assert r2.put_calls[0]["content_type"] == "application/json"

    def test_the_sidecar_is_the_complete_recipe(self, authed_client, r2):
        """§9.3: enough to regenerate with no other state — which is what makes
        any replica able to serve or re-synthesize an artifact it never saw."""
        import json

        authed_client.post(ENDPOINT, json={"text": "In the beginning"})
        stored = json.loads(next(iter(r2.objects.values()))["body"])
        assert stored == {
            "recipe_version": "v1",
            "text": "In the beginning",
            "voice": "Kore",
            "model": "test-tts-model",
            "format": "ogg-opus",
            "lang_code": None,
        }

    def test_repeating_the_call_is_an_idempotent_no_op(self, authed_client, r2):
        first = authed_client.post(ENDPOINT, json={"text": "hello"})
        second = authed_client.post(ENDPOINT, json={"text": "hello"})

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        # Two attempts, both conditional, one stored object: the second PUT
        # lost the race by design and that is success, not an error.
        assert len(r2.put_calls) == 2
        assert all(call["if_none_match"] == "*" for call in r2.put_calls)
        assert len(r2.objects) == 1

    def test_generate_never_synthesizes(self, authed_client, provider):
        """T8. Generation is deferred to the first get-audio, which is what
        makes prefetching a verse the user never reaches nearly free."""
        authed_client.post(ENDPOINT, json={"text": "hello"})
        assert provider.synthesize_calls == []

    def test_lang_code_spellings_share_one_artifact(self, authed_client):
        urls = {
            authed_client.post(
                ENDPOINT, json={"text": "hello", "lang_code": code}
            ).json()["audio_url"]
            for code in ("en", "eng", "ENG")
        }
        urls.add(
            authed_client.post(ENDPOINT, json={"text": "hello"}).json()["audio_url"]
        )
        assert len(urls) == 1


# ---------------------------------------------------------------------------
# Validation — T27: this service owns the length limit
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_text_is_a_400_invalid_request(self, authed_client):
        response = authed_client.post(ENDPOINT, json={"text": ""})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.TTS_INVALID_REQUEST

    def test_whitespace_only_text_is_also_rejected(self, authed_client):
        response = authed_client.post(ENDPOINT, json={"text": "   \n\t "})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.TTS_INVALID_REQUEST

    def test_text_at_exactly_the_maximum_is_accepted(self, authed_client, settings):
        response = authed_client.post(
            ENDPOINT, json={"text": "a" * settings.tts_max_text_length}
        )
        assert response.status_code == 200, response.text

    def test_one_character_over_the_maximum_is_rejected(
        self, authed_client, settings, r2
    ):
        maximum = settings.tts_max_text_length
        response = authed_client.post(ENDPOINT, json={"text": "a" * (maximum + 1)})

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == ErrorCode.TTS_TEXT_TOO_LONG
        # The configured maximum must be nameable by the caller: the tripwire is
        # env-tunable, so "too long" without a number is unactionable.
        assert str(maximum) in error["message"]
        assert error["details"] == {
            "max_length": maximum,
            "actual_length": maximum + 1,
        }
        # Nothing was stored and nothing was billed.
        assert r2.put_calls == []

    def test_an_unknown_field_is_a_client_bug(self, authed_client):
        """`extra="forbid"`, matching fluent-api's `.strict()`. Notably this is
        how a re-added `pacing` field would fail loudly instead of being
        silently ignored."""
        response = authed_client.post(
            ENDPOINT, json={"text": "hello", "pacing": {"mode": "slow"}}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR

    def test_missing_text_is_a_422(self, authed_client):
        assert authed_client.post(ENDPOINT, json={}).status_code == 422

    def test_an_unknown_format_is_rejected(self, authed_client):
        response = authed_client.post(
            ENDPOINT, json={"text": "hello", "format": "flac"}
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Auth and configuration
# ---------------------------------------------------------------------------


class TestAuthAndConfiguration:
    def test_missing_api_key_is_401(self, client, service):
        """The money path stays authenticated end to end: this is the call that
        authorizes spending, so an unauthenticated one must not write a sidecar."""
        app.dependency_overrides[get_tts_service] = lambda: service
        try:
            response = client.post(ENDPOINT, json={"text": "hello"})
        finally:
            app.dependency_overrides.pop(get_tts_service, None)
        assert response.status_code == 401

    def test_unconfigured_storage_is_a_503_not_a_boot_failure(
        self, client, fake_api_key
    ):
        """A deployment with no audio bucket must still serve everything else —
        so the failure is per-request, on TTS routes only, and it names itself."""

        def unconfigured_service() -> TtsService:
            settings = tts_settings(r2_tts_bucket=None)
            # Mirrors the real dependency: the store is what refuses to build.
            return TtsService(
                settings=settings,
                store=build_artifact_store(settings),
                provider=FakeTtsProvider(),
                compressor=FakeCompressor(),
            )

        app.dependency_overrides[require_api_key] = lambda: fake_api_key
        app.dependency_overrides[get_tts_service] = unconfigured_service
        try:
            response = client.post(ENDPOINT, json={"text": "hello"})
            health = client.get("/health")
        finally:
            app.dependency_overrides.pop(require_api_key, None)
            app.dependency_overrides.pop(get_tts_service, None)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == ErrorCode.TTS_STORAGE_NOT_CONFIGURED
        # The rest of the service is unaffected.
        assert health.status_code == 200
