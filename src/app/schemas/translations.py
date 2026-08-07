from pydantic import BaseModel, Field


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
