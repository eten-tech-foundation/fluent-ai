from pydantic import BaseModel, ConfigDict, Field, model_validator


class SuggestionTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_unit_id: int = Field(alias="projectUnitId", gt=0)
    bible_id: int = Field(alias="bibleId", gt=0)
    book_code: str = Field(alias="bookCode", pattern=r"^[A-Za-z0-9]+$")
    chapter_number: int = Field(alias="chapterNumber", gt=0)
    verse_start: int = Field(alias="verseStart", gt=0)
    verse_end: int = Field(alias="verseEnd", gt=0)

    @model_validator(mode="after")
    def _verse_range_is_ordered(self) -> "SuggestionTriggerRequest":
        if self.verse_start > self.verse_end:
            raise ValueError(
                f"verse_start ({self.verse_start}) must be <= verse_end ({self.verse_end})"
            )
        return self


class SuggestionTriggerResponse(BaseModel):
    message: str
