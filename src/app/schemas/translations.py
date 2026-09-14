from unicodedata import category

from pydantic import BaseModel, Field, field_validator


class ContextVerse(BaseModel):
    verse_id: str
    source_text: str
    target_text: str


class VerseToTranslate(BaseModel):
    verse_id: str
    source_text: str


class TranslateRequest(BaseModel):
    target_language_name: str = Field(
        description="Name of the target language for the prompt instructions"
    )
    context_verses: list[ContextVerse] = Field(
        default_factory=list,
        description="Previously translated verses serving as context",
    )
    verses_to_translate: list[VerseToTranslate] = Field(
        description="The new verses to translate"
    )


class TranslatedVerseResponse(BaseModel):
    verse_id: str
    target_text: str


class TranslationResult(BaseModel):
    translations: list[TranslatedVerseResponse]


class TranslateHeadingRequest(BaseModel):
    target_language_name: str
    source_title: str = Field(min_length=1)
    context_verses: list[ContextVerse] = Field(default_factory=list)
    source_verses: list[VerseToTranslate] = Field(min_length=1)

    @field_validator("source_title")
    @classmethod
    def _source_title_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A source title is required to translate a heading")
        return value.strip()


class HeadingTranslationResult(BaseModel):
    suggested_text: str = Field(min_length=1, max_length=300)

    @field_validator("suggested_text", mode="before")
    @classmethod
    def _heading_is_plain_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Heading must be text")
        if any(
            char in "\\\u2028\u2029" or category(char) in {"Cc", "Cs"} for char in value
        ):
            raise ValueError(
                "Heading must be one line without control or USFM characters"
            )
        value = value.strip()
        if not value or len(value.encode("utf-16-le")) // 2 > 300:
            raise ValueError("Heading must contain 1 to 300 UTF-16 code units")
        return value
