# src/app/schemas/tts.py
"""
Pydantic wire models for the Source-TTS contract (proposal §7.1).

── snake_case, no aliases ───────────────────────────────────────────────────
The wire field names are `text` / `voice` / `format` / `lang_code` /
`audio_url` — identical to the Python attribute names, so this boundary needs
no aliases at all. fluent-api mirrors these names verbatim (as it already does
for greek-room under decision D8) and passes the response body through
unmodified, so a camelCase spelling here would have forced a translation step
into the one component §12.2 forbids from touching the body.

── The backend knows nothing about scripture (T6) ───────────────────────────
There is no verse, chapter, project or bible in this contract — only text.
That is what lets a future caller speak instructions or resource notes with no
backend change, and what makes one artifact shareable across projects.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #

TtsFormat = Literal["ogg-opus", "mp3"]
"""Compressed formats the compression tail can produce (§7.1).

Deliberately duplicated as a `Literal` in `Settings.tts_default_format`:
config must not import the service layer (the service layer imports config),
and the pair is small enough that a mismatch is caught by mypy at the one
place they meet — `build_recipe()`.
"""

FORMAT_EXTENSIONS: dict[str, str] = {"ogg-opus": "ogg", "mp3": "mp3"}
"""Compressed-object file extension per format.

`ogg-opus` is Opus *inside an Ogg container*, hence `.ogg`: the format name
describes the codec choice, the extension describes the container. Both are
needed, and conflating them is how a `.opus` key that nothing serves gets
created.
"""

FORMAT_CONTENT_TYPES: dict[str, str] = {"ogg-opus": "audio/ogg", "mp3": "audio/mpeg"}
"""Content-Type for the compressed object (set at PUT time, §10.1)."""

STREAMING_EXTENSION = "wav"
"""The `audio_url` extension during the generation era (§7.2).

One artifact, two representation eras: `{hash}.wav` streams live while the
clip is being generated, and once the compressed object exists the same path
answers a 302 to `{hash}.{ogg|mp3}` — an extension *swap*, not a format
request. The hash already pins the format, so this extension is never a
content negotiation.
"""


# --------------------------------------------------------------------------- #
# generate — request
# --------------------------------------------------------------------------- #


class TtsGenerateRequest(BaseModel):
    """Input payload for POST /tts/generate.

    `extra="forbid"` mirrors fluent-api's `.strict()`: an unknown field is a
    client bug worth surfacing rather than silently dropping, and the additive
    direction stays safe because a new field is added to both services in one
    change. (There is no `pacing` field: the slot reserved by T11 was removed
    on 2026-08-11, before anything shipped, because it had no defined values
    and therefore no implementable behaviour.)

    Note what is *not* validated here: `text` length. Both bounds are enforced
    in the service so that each failure gets its own contract error code —
    `TTS_INVALID_REQUEST` for empty, `TTS_TEXT_TOO_LONG` (naming the
    configured maximum) for oversized — which a schema violation would flatten
    into one 422 VALIDATION_ERROR.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        description=(
            "Exact visible text to recite. Rejected beyond TTS_MAX_TEXT_LENGTH."
        ),
        examples=["In the beginning God created the heavens and the earth."],
    )
    voice: str | None = Field(
        default=None,
        description=(
            "Requested provider voice. Omitted by the v1 frontend, in which "
            "case the configured TTS_VOICE applies."
        ),
    )
    format: TtsFormat | None = Field(
        default=None,
        description=(
            "Compressed format to produce. Omitted by default; fluent-ai then "
            "resolves TTS_DEFAULT_FORMAT before hashing, so 'unspecified' "
            "never exists internally."
        ),
    )
    lang_code: str | None = Field(
        default=None,
        description=(
            "ISO 639-3 language hint, sent whenever the caller knows it (T18). "
            "Advisory: for a provider that ignores it, it is normalized out of "
            "the artifact identity."
        ),
        examples=["eng"],
    )


# --------------------------------------------------------------------------- #
# generate — response
# --------------------------------------------------------------------------- #


class TtsGenerateResponse(BaseModel):
    """Success body for POST /tts/generate.

    ⚠️ `audio_url` is **sibling-relative** (`audio/{hash}.wav`), resolved by
    the caller against the URL it actually called. That is what keeps the
    serving choice server-side: the browser called fluent-api, so its audio
    fetch goes to fluent-api, while a future direct consumer of fluent-ai
    resolves to fluent-ai — with no contract change and without fluent-ai
    knowing any consumer's public base URL. It requires `generate` and
    `audio/{hash}` to stay siblings under one prefix on *both* services.

    There is deliberately no duration field: a streaming first listen has no
    knowable duration, and once compressed the container header carries the
    exact value for free (T22, §6.2). Do not add one back.
    """

    audio_url: str = Field(
        description=(
            "Sibling-relative reference to the audio, resolved against the request URL."
        ),
        examples=["audio/9f2ac1d47bfe3a5c8e1d0b6a4f7c2e91.wav"],
    )
