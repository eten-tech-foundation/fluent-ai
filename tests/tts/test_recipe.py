"""
tests/tts/test_recipe.py — artifact identity (source-tts proposal §9.1).

The properties under test are the ones a later change could break silently:
which fields participate in identity, that JSON key order cannot influence a
hash, and that spoken text is never altered on its way into the recipe.
"""

import re

import pytest

from app.schemas.tts import TtsGenerateRequest
from app.services.tts.recipe import (
    RECIPE_VERSION,
    TtsRecipe,
    artifact_hash,
    build_recipe,
    normalize_lang_code,
)
from tests.tts.fakes import FakeTtsProvider, tts_settings


SECRET = "test-hash-secret"


def hash_for(payload: dict, *, provider: FakeTtsProvider | None = None) -> str:
    settings = tts_settings()
    recipe = build_recipe(
        TtsGenerateRequest(**payload),
        settings=settings,
        provider=provider or FakeTtsProvider(),
    )
    return artifact_hash(recipe, secret=SECRET)


class TestCanonicalRecipe:
    def test_canonical_string_shape(self):
        recipe = TtsRecipe(
            text="In the beginning",
            model="test-tts-model",
            format="ogg-opus",
            voice="Kore",
            lang_code="eng",
        )
        assert recipe.canonical_string() == (
            "v1:In the beginning\x1fKore\x1ftest-tts-model\x1fogg-opus\x1feng"
        )

    def test_absent_fields_render_as_the_canonical_placeholder(self):
        recipe = TtsRecipe(text="text", model="m", format="mp3")
        assert recipe.canonical_string() == "v1:text\x1f-\x1fm\x1fmp3\x1f-"

    def test_version_prefix_is_present_and_not_a_request_field(self):
        assert RECIPE_VERSION == "v1"
        recipe = TtsRecipe(text="t", model="m", format="mp3")
        assert recipe.canonical_string().startswith("v1:")
        # The version is server-side only: it must never appear on the wire.
        assert "recipe_version" not in TtsGenerateRequest.model_fields


class TestArtifactHash:
    def test_hash_is_lowercase_hex_sha256(self):
        digest = hash_for({"text": "hello"})
        assert re.fullmatch(r"[0-9a-f]{64}", digest)

    def test_hash_is_stable_across_request_field_ordering(self):
        """JSON key order must not reach the hash (§9.1: canonical recipe)."""
        a = hash_for({"text": "hello", "voice": "Kore", "format": "mp3"})
        b = hash_for({"format": "mp3", "voice": "Kore", "text": "hello"})
        assert a == b

    def test_secret_participates(self):
        recipe = TtsRecipe(text="t", model="m", format="mp3")
        assert artifact_hash(recipe, secret="one") != artifact_hash(
            recipe, secret="two"
        )

    def test_empty_secret_is_refused(self):
        """A name computed without the secret would be a bare hash of public
        text, which is the one thing HMAC identity exists to prevent."""
        with pytest.raises(ValueError, match="TTS_HASH_SECRET"):
            artifact_hash(TtsRecipe(text="t", model="m", format="mp3"), secret="")


class TestLangCodeNormalization:
    def test_gemini_collapses_en_eng_and_absent_to_one_artifact(self):
        """T18/K1: for Gemini the hint cannot change the bytes, so all three
        spellings must share one artifact — and therefore one billing event."""
        digests = {
            hash_for({"text": "hello", "lang_code": "en"}),
            hash_for({"text": "hello", "lang_code": "eng"}),
            hash_for({"text": "hello"}),
        }
        assert len(digests) == 1

    def test_a_provider_that_uses_lang_code_keeps_it_in_identity(self):
        provider = FakeTtsProvider(ignored_fields=frozenset())
        distinct = {
            hash_for({"text": "hello", "lang_code": "eng"}, provider=provider),
            hash_for({"text": "hello", "lang_code": "fra"}, provider=provider),
            hash_for({"text": "hello"}, provider=provider),
        }
        assert len(distinct) == 3

    def test_case_and_whitespace_are_folded_but_the_code_is_not_invented(self):
        provider = FakeTtsProvider(ignored_fields=frozenset())
        assert hash_for(
            {"text": "hello", "lang_code": " ENG "}, provider=provider
        ) == hash_for({"text": "hello", "lang_code": "eng"}, provider=provider)
        assert normalize_lang_code("   ") is None
        assert normalize_lang_code(None) is None

    def test_text_is_never_altered(self):
        """Only structurally absent optional fields normalize; text does not."""
        text = "  In THE beginning,   God\u00a0created.  "
        recipe = build_recipe(
            TtsGenerateRequest(text=text),
            settings=tts_settings(),
            provider=FakeTtsProvider(),
        )
        assert recipe.text == text
        assert hash_for({"text": text}) != hash_for({"text": text.strip()})


class TestFormatResolution:
    def test_omitted_format_resolves_to_the_configured_default(self):
        settings = tts_settings(tts_default_format="mp3")
        recipe = build_recipe(
            TtsGenerateRequest(text="hello"),
            settings=settings,
            provider=FakeTtsProvider(),
        )
        assert recipe.format == "mp3"

    def test_explicit_format_equal_to_the_default_dedups_with_omitting(self):
        """CB2: resolve before hashing, so "unspecified" never exists inside."""
        assert hash_for({"text": "hello", "format": "ogg-opus"}) == hash_for(
            {"text": "hello"}
        )

    def test_different_format_is_a_different_artifact(self):
        assert hash_for({"text": "hello", "format": "mp3"}) != hash_for(
            {"text": "hello", "format": "ogg-opus"}
        )


class TestVoiceResolution:
    def test_omitted_voice_resolves_to_the_configured_voice(self):
        recipe = build_recipe(
            TtsGenerateRequest(text="hello"),
            settings=tts_settings(tts_voice="Puck"),
            provider=FakeTtsProvider(),
        )
        assert recipe.voice == "Puck"

    def test_voice_is_byte_affecting_for_gemini(self):
        assert hash_for({"text": "hello", "voice": "Puck"}) != hash_for(
            {"text": "hello", "voice": "Kore"}
        )

    def test_model_change_renames_future_artifacts(self):
        """Changing TTS_MODEL must not reinterpret existing objects."""
        first = build_recipe(
            TtsGenerateRequest(text="hello"),
            settings=tts_settings(tts_model="model-a"),
            provider=FakeTtsProvider(),
        )
        second = build_recipe(
            TtsGenerateRequest(text="hello"),
            settings=tts_settings(tts_model="model-b"),
            provider=FakeTtsProvider(),
        )
        assert artifact_hash(first, secret=SECRET) != artifact_hash(
            second, secret=SECRET
        )


class TestProviderDeclarationGuard:
    @pytest.mark.parametrize("field", ["text", "format", "model"])
    def test_a_provider_may_not_normalize_content_or_format_away(self, field):
        """`text` is the content and `format` selects the stored object, so
        neither may leave artifact identity — a provider that says otherwise is
        a bug and must fail loudly."""
        with pytest.raises(ValueError, match="normalizable set"):
            build_recipe(
                TtsGenerateRequest(text="hello"),
                settings=tts_settings(),
                provider=FakeTtsProvider(ignored_fields=frozenset({field})),
            )


class TestSidecarRoundTrip:
    def test_sidecar_carries_the_complete_recipe(self):
        recipe = build_recipe(
            TtsGenerateRequest(text="hello", lang_code="eng"),
            settings=tts_settings(),
            provider=FakeTtsProvider(),
        )
        body = recipe.to_sidecar_dict()
        assert body == {
            "recipe_version": "v1",
            "text": "hello",
            "voice": "Kore",
            "model": "test-tts-model",
            "format": "ogg-opus",
            # Normalized out for Gemini, and null in the sidecar for the same
            # reason: a field that cannot affect the bytes can fall back to
            # configuration when the artifact is regenerated.
            "lang_code": None,
        }

    def test_a_recipe_rebuilt_from_its_sidecar_hashes_identically(self):
        """This is what makes any replica able to regenerate the artifact from
        durable state alone (§7.2 rung 3)."""
        original = build_recipe(
            TtsGenerateRequest(text="hello", voice="Puck", format="mp3"),
            settings=tts_settings(),
            provider=FakeTtsProvider(),
        )
        rebuilt = TtsRecipe.from_sidecar_dict(original.to_sidecar_dict())
        assert rebuilt == original
        assert artifact_hash(rebuilt, secret=SECRET) == artifact_hash(
            original, secret=SECRET
        )

    def test_sidecar_has_no_timestamp_or_user_identity(self):
        """Two properties in one absence: the body is byte-identical on every
        replica (so a conditional-PUT conflict is provably a no-op), and it
        leaks nothing about who asked, since it is publicly fetchable."""
        recipe = build_recipe(
            TtsGenerateRequest(text="hello"),
            settings=tts_settings(),
            provider=FakeTtsProvider(),
        )
        body = recipe.to_sidecar_dict()
        assert not any(key in body for key in ("created_at", "user_id", "requested_by"))
