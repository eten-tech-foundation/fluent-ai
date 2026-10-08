# src/app/services/tts/recipe.py
"""
Artifact identity: a canonical synthesis recipe and its HMAC (proposal §9.1).

The identity is **recipe-addressed**, not byte-addressed: the HMAC names the
recipe, and the stored object is one render of it. A nondeterministic provider
may render the same recipe differently on two attempts — every render is an
equally valid reading of the same text — and the first-writer-wins conditional
PUT (§10.1) decides which render becomes durable.

Why HMAC and not a plain hash: scripture text is public, so a bare content hash
would be computable by anyone, and the artifact names are served from a public
R2 domain. The server secret is what makes "knowing a hash" a capability
(§7.3, §11.1).
"""

import hmac
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from app.schemas.tts import TtsFormat, TtsGenerateRequest


if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings
    from app.services.tts.provider import TtsProvider


RECIPE_VERSION = "v1"
"""Version prefix injected server-side; never a request field, never on the API.

Any future change to the recipe's *composition* bumps this, which cleanly
separates old and new artifact namespaces instead of quietly reinterpreting
existing objects. (Adding a byte-affecting field later is exactly such a
change: it would make this `v2`.)
"""

_FIELD_SEPARATOR = "\x1f"
"""ASCII Unit Separator — the canonical field delimiter of the recipe string."""

_ABSENT = "-"
"""Canonical placeholder for a field that is absent or normalized out."""

_NORMALIZABLE_FIELDS = frozenset({"voice", "lang_code"})
"""The only fields a provider may declare non-byte-affecting.

`text` is the content itself, and `format` is the *compression tail's*
parameter (§10.1) rather than a synthesis knob — it decides which object
extension the hash resolves to, so blanking it would let one hash mean both an
`.ogg` and an `.mp3` object. A provider that declares either is a bug, and
`build_recipe` says so loudly rather than silently ignoring the declaration.
"""


@dataclass(frozen=True)
class TtsRecipe:
    """Everything needed to (re)produce one artifact, and nothing else.

    Frozen because identity depends on it: a recipe that could be mutated after
    hashing would let the sidecar and the hash disagree.

    `voice` and `lang_code` are `None` when the provider declared them unable
    to affect its output bytes. That is not data loss — a field that cannot
    change the audio can safely fall back to configuration at regeneration
    time, which is precisely why it was blanked.
    """

    text: str
    model: str
    format: TtsFormat
    voice: str | None = None
    lang_code: str | None = None
    recipe_version: str = RECIPE_VERSION

    def canonical_string(self) -> str:
        """Render the recipe in its one canonical form, per §9.1:

            v1:{text}\\x1f{voice}\\x1f{model}\\x1f{format}\\x1f{lang_code}

        Field *order* is fixed here and nowhere else, which is what makes the
        hash independent of JSON key order in the request.

        A noted, bounded ambiguity: text is not length-prefixed, so a caller
        who deliberately embeds `\\x1f` in `text` could construct two different
        recipes with the same canonical string. The blast radius is only that
        caller's own artifacts (they must authenticate to reach this code, and
        the HMAC secret keeps the names unguessable from outside), so v1 keeps
        the documented recipe shape. Length-prefixing is the fix if that ever
        stops being true, and it would ship as `v2:`.
        """
        fields = (
            self.text,
            self.voice or _ABSENT,
            self.model,
            self.format,
            self.lang_code or _ABSENT,
        )
        return f"{self.recipe_version}:{_FIELD_SEPARATOR.join(fields)}"

    def to_sidecar_dict(self) -> dict[str, str | None]:
        """The request sidecar body (§9.3): the complete recipe, nothing more.

        No timestamp and no user identifier — the first deliberately, so the
        body is byte-identical for a given hash on every replica (a conditional
        PUT conflict is then provably a no-op rather than a lost write), and the
        second because the sidecar is publicly fetchable.
        """
        return {
            "recipe_version": self.recipe_version,
            "text": self.text,
            "voice": self.voice,
            "model": self.model,
            "format": self.format,
            "lang_code": self.lang_code,
        }

    @classmethod
    def from_sidecar_dict(cls, body: dict) -> "TtsRecipe":
        """Rebuild a recipe from its sidecar, for regeneration on any replica.

        This is the property that makes multi-replica serving self-healing
        (§7.2 rung 3): a replica that has never seen the original request can
        reproduce the artifact from durable state alone.
        """
        return cls(
            text=body["text"],
            model=body["model"],
            format=body["format"],
            voice=body.get("voice"),
            lang_code=body.get("lang_code"),
            recipe_version=body.get("recipe_version", RECIPE_VERSION),
        )


def normalize_lang_code(value: str | None) -> str | None:
    """Canonicalize a language code, or return None when there is none.

    Codes are case-insensitive identifiers (`eng` == `ENG`), so folding case
    keeps two clients that spell the hint differently on one artifact and one
    billing event. This is not in tension with "spoken text is never altered"
    (§9.1): `text` is untouched — only this identifier is canonicalized.
    """
    if value is None:
        return None
    trimmed = value.strip().lower()
    return trimmed or None


def build_recipe(
    request: TtsGenerateRequest,
    *,
    settings: "Settings",
    provider: "TtsProvider",
) -> TtsRecipe:
    """Resolve a wire request into the recipe that will be hashed and stored.

    Two resolutions happen here, both *before* hashing (§7.1/CB2):

    * an omitted `format` becomes `TTS_DEFAULT_FORMAT`, so "unspecified" never
      exists internally and an explicit request equal to the default dedups
      with an omitting one instead of creating a twin artifact;
    * an omitted `voice` becomes `TTS_VOICE`.

    Then the provider's declared non-byte-affecting fields are blanked, so
    identity tracks exactly the inputs that can change the audio.
    """
    ignored = frozenset(provider.non_byte_affecting_fields())
    unsupported = ignored - _NORMALIZABLE_FIELDS
    if unsupported:
        raise ValueError(
            "provider declared non-byte-affecting fields outside the "
            f"normalizable set: {sorted(unsupported)}. `text` is the content "
            "itself and `format` selects the stored object, so neither may be "
            "normalized out of artifact identity (§9.1)."
        )

    voice = request.voice or settings.tts_voice
    lang_code = normalize_lang_code(request.lang_code)

    return TtsRecipe(
        text=request.text,
        model=settings.tts_model,
        format=request.format or settings.tts_default_format,
        voice=None if "voice" in ignored else voice,
        lang_code=None if "lang_code" in ignored else lang_code,
    )


def artifact_hash(recipe: TtsRecipe, *, secret: str) -> str:
    """HMAC-SHA256 of the canonical recipe, hex-encoded.

    64 lowercase hex characters, which is what fluent-api's `{hash}.{ext}` path
    validator accepts.
    """
    if not secret:
        raise ValueError(
            "TTS_HASH_SECRET is empty; an artifact name computed without it "
            "would be a bare hash of public text (§9.1)."
        )
    return hmac.new(
        secret.encode("utf-8"),
        recipe.canonical_string().encode("utf-8"),
        sha256,
    ).hexdigest()
