from pydantic import BaseModel, ConfigDict, Field


class SuggestionTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_unit_id: int = Field(alias="projectUnitId")
    bible_id: int = Field(alias="bibleId")
    book_code: str = Field(alias="bookCode")
    chapter_number: int = Field(alias="chapterNumber")
    verse_start: int = Field(alias="verseStart")
    verse_end: int = Field(alias="verseEnd")


class SuggestionTriggerResponse(BaseModel):
    message: str
