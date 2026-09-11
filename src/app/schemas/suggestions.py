from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SuggestionTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_unit_id: int = Field(alias="projectUnitId", gt=0)
    bible_id: int = Field(alias="bibleId", gt=0)
    book_code: str = Field(alias="bookCode", pattern=r"^[A-Za-z0-9]+$")
    chapter_number: int = Field(alias="chapterNumber", gt=0)
    verse_start: int = Field(alias="verseStart", gt=0)
    verse_end: int = Field(alias="verseEnd", gt=0)
    pericope_number: str | None = Field(
        default=None, alias="pericopeNumber", min_length=1, max_length=100
    )
    pericope_set_id: int | None = Field(default=None, alias="pericopeSetId", gt=0)

    @field_validator("pericope_number")
    @classmethod
    def _pericope_number_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("pericopeNumber must not be blank")
        return value

    @model_validator(mode="after")
    def _heading_identity_is_complete(self) -> "SuggestionTriggerRequest":
        if (self.pericope_number is None) != (self.pericope_set_id is None):
            raise ValueError(
                "pericopeNumber and pericopeSetId must be provided together"
            )
        return self

    @model_validator(mode="after")
    def _verse_range_is_ordered(self) -> "SuggestionTriggerRequest":
        if self.verse_start > self.verse_end:
            raise ValueError(
                f"verse_start ({self.verse_start}) must be <= verse_end ({self.verse_end})"
            )
        return self


class SuggestionTriggerResponse(BaseModel):
    message: str


class SectionHeadingContext(BaseModel):
    """Source metadata supplied by fluent-api for a heading-only job."""

    pericope_number: str = Field(alias="pericopeNumber", min_length=1, max_length=100)
    bible_text_id: int = Field(alias="bibleTextId", gt=0, strict=True)
    pericope_set_id: int = Field(alias="pericopeSetId", gt=0, strict=True)
    source_title: str = Field(alias="sourceTitle", min_length=1)
