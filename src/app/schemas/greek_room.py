# src/app/schemas/greek_room.py
"""
Pydantic request/result schemas for the Greek-Room tool family.

Field naming follows Python conventions (snake_case); the underlying
greek-room library uses hyphenated JSON-RPC keys ("snt-id", "lang-code")
which are an implementation detail of the service layer and never leak
to callers.
"""

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Repeated Words — request
# --------------------------------------------------------------------------- #


class VerseInput(BaseModel):
    """A single verse to be checked.

    Attributes:
        snt_id: Scripture reference, e.g. "GEN 1:1".
        text:   Verse text in the project language.
    """

    snt_id: str = Field(..., description="Scripture reference, e.g. 'GEN 1:1'.")
    text: str = Field(..., description="Verse text in the project language.")


class RepeatedWordsRequest(BaseModel):
    """Input payload for POST /tools/greek-room/repeated-words.

    Attributes:
        lang_code:    ISO 639-3 language code, e.g. "eng".
        lang_name:    Human-readable language name, e.g. "English".
        project_id:   Caller-supplied project identifier.
        project_name: Caller-supplied human label for the project.
        verses:       Corpus of verses to check.
    """

    lang_code: str = Field(..., description="ISO 639-3 language code, e.g. 'eng'.")
    lang_name: str = Field(..., description="Human-readable language name.")
    project_id: str = Field(..., description="Caller-supplied project identifier.")
    project_name: str = Field(..., description="Caller-supplied project label.")
    verses: list[VerseInput] = Field(..., description="Corpus of verses to check.")


# --------------------------------------------------------------------------- #
# Repeated Words — result
# --------------------------------------------------------------------------- #


class RepeatedWordsFinding(BaseModel):
    """A single repeated-words finding within a verse.

    Attributes:
        snt_id:         Scripture reference where the duplicate was found.
        repeated_word:  The duplicated token in lowercased "word word" form.
        surf:           The exact surface text as it appeared in the verse,
                        preserving original casing and punctuation.
        start_position: 0-based character offset of the duplicate within the verse.
        legitimate:     True if the duplicate matches a known legitimate-duplicate
                        entry for the language (e.g. "truly truly" in English);
                        False if it is likely an error.
        severity:       0.1 for legitimate duplicates, 0.5 for suspicious ones.
    """

    snt_id: str
    repeated_word: str
    surf: str
    start_position: int
    legitimate: bool
    severity: float


class RepeatedWordsSummary(BaseModel):
    """Aggregate counts across the corpus.

    Attributes:
        total_findings:   Number of repeated-words instances detected.
        legitimate_count: Subset of total_findings flagged as legitimate.
        verse_count:      Number of verses submitted for checking.
    """

    total_findings: int
    legitimate_count: int
    verse_count: int


class RepeatedWordsResult(BaseModel):
    """Result body returned inside the ToolJobResponse envelope.

    The `provider` and `check` fields preserve the upstream library's
    own naming so a caller debugging an issue can correlate against
    upstream documentation without ambiguity. They are deliberately
    not named `tool` to avoid collision with the envelope's `tool`
    field (which carries the Fluent-AI tool identifier).
    """

    lang_code: str
    provider: str = Field(
        default="GreekRoom",
        description="Upstream library name (distinct from the envelope's `tool` field).",
    )
    check: str = Field(
        default="RepeatedWords",
        description="Upstream check name within the provider.",
    )
    findings: list[RepeatedWordsFinding]
    summary: RepeatedWordsSummary
