from pydantic import BaseModel


class SuggestionTriggerRequest(BaseModel):
    projectUnitId: int
    bibleId: int
    bookCode: str
    chapterNumber: int
    verseStart: int
    verseEnd: int


class SuggestionTriggerResponse(BaseModel):
    message: str
