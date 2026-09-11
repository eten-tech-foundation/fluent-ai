import json
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas.translations import (
    ContextVerse,
    HeadingTranslationResult,
    TranslateHeadingRequest,
    VerseToTranslate,
)
from app.services.translation_service import TranslationService


def heading_request() -> TranslateHeadingRequest:
    return TranslateHeadingRequest(
        target_language_name="Spanish",
        source_title="Jesus feeds the crowd",
        context_verses=[
            ContextVerse(verse_id="MAT_14_12", source_text="Jesus", target_text="Jesús")
        ],
        source_verses=[
            VerseToTranslate(
                verse_id="MAT_14_13", source_text="The crowd followed him."
            ),
            VerseToTranslate(verse_id="MAT_14_21", source_text="They all ate."),
        ],
    )


async def test_heading_prompt_preserves_source_title_and_all_pericope_context():
    client = AsyncMock()
    client.generate_content.return_value = (
        '{"suggested_text":"  Jesús alimenta a la multitud  "}'
    )
    service = TranslationService(Mock(spec=Settings), client)

    result = await service.translate_heading(heading_request())

    assert result.suggested_text == "Jesús alimenta a la multitud"
    call = client.generate_content.call_args.kwargs
    assert json.loads(call["prompt"]) == heading_request().model_dump()
    assert "Translate ONLY the source section" in call["system_instruction"]
    assert "Do not translate verses" in call["system_instruction"]
    assert "ALL source_verses" in call["system_instruction"]
    assert call["response_schema"] is HeadingTranslationResult
    assert call["response_mime_type"] == "application/json"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "A\nB",
        "A\rB",
        "A\tB",
        "A\x00B",
        "A\x7fB",
        "A\u2028B",
        "A\u2029B",
        "\\s1 Heading",
        "x" * 301,
        "😀" * 151,
        "\ud800",
        None,
        12,
    ],
)
async def test_heading_service_rejects_unsafe_output_for_worker_retry(text):
    client = AsyncMock()
    client.generate_content.return_value = json.dumps({"suggested_text": text})
    service = TranslationService(Mock(spec=Settings), client)

    with pytest.raises(ValidationError):
        await service.translate_heading(heading_request())


@pytest.mark.parametrize("text", ["x" * 300, "😀" * 150, "Jesus’ ministry", "क्\u200dष"])
def test_heading_output_accepts_boundary_and_natural_script_characters(text):
    assert HeadingTranslationResult(suggested_text=f" {text} ").suggested_text == text


@pytest.mark.parametrize("response", ["not JSON", '{"translations":[]}', "{}"])
async def test_heading_service_rejects_wrong_response_shape(response):
    client = AsyncMock()
    client.generate_content.return_value = response
    service = TranslationService(Mock(spec=Settings), client)
    with pytest.raises(ValidationError):
        await service.translate_heading(heading_request())


def test_heading_request_requires_a_source_title():
    with pytest.raises(ValidationError):
        TranslateHeadingRequest(
            target_language_name="Spanish",
            source_title="   ",
            source_verses=heading_request().source_verses,
        )
