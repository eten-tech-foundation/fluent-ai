from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.schemas.translations import HeadingTranslationResult, TranslationResult
from app.worker.suggestion_processor import process_job


@pytest.fixture
def payload():
    return {
        "projectUnitId": 1,
        "bibleId": 2,
        "bookCode": "MAT",
        "chapterNumber": 14,
        "verseStart": 13,
        "verseEnd": 21,
        "pericopeNumber": "14.2",
        "pericopeSetId": 7,
    }


@pytest.fixture
def context():
    return {
        "targetLanguageName": "Spanish",
        "contextVerses": [],
        "sourceVerses": [
            {"id": 42, "verse_number": 13, "text": "The crowd followed him."},
            {"id": 50, "verse_number": 21, "text": "They all ate."},
        ],
        "sectionHeading": {
            "pericopeNumber": "14.2",
            "pericopeSetId": 7,
            "bibleTextId": 42,
            "sourceTitle": "Jesus feeds the crowd",
        },
    }


@pytest.fixture
def service():
    return SimpleNamespace(
        settings=SimpleNamespace(
            api_base_url="http://fluent-api:9999/",
            api_service_key="test-key",
            google_ai_model="gemini-test",
        ),
        translate_heading=AsyncMock(
            return_value=HeadingTranslationResult(
                suggested_text="Jesús alimenta a la multitud"
            )
        ),
        translate_verses=AsyncMock(),
    )


@pytest.fixture
def api(monkeypatch, context):
    calls = []

    async def post(_client, url, **kwargs):
        calls.append((url, deepcopy(kwargs)))
        return httpx.Response(
            status_code=200,
            json=context if url.endswith("/context") else {},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return calls


async def test_heading_job_uses_full_context_and_pushes_only_heading(
    db_session, make_job, payload, context, service, api
):
    job = await make_job(payload=payload)
    await process_job(db_session, job, service)
    await db_session.refresh(job)

    assert job.status == "completed"
    assert job.retry_count == 0
    assert len(api) == 2
    assert api[0][1]["json"] == payload
    assert api[0][1]["headers"]["Authorization"] == "Bearer test-key"
    request = service.translate_heading.call_args.args[0]
    assert request.source_title == context["sectionHeading"]["sourceTitle"]
    assert request.target_language_name == "Spanish"
    assert [v.source_text for v in request.source_verses] == [
        v["text"] for v in context["sourceVerses"]
    ]
    assert api[1][1]["json"] == {
        "items": [],
        "heading": {
            "projectUnitId": 1,
            "bibleTextId": 42,
            "pericopeNumber": "14.2",
            "pericopeSetId": 7,
            "suggestedText": "Jesús alimenta a la multitud",
            "modelInfo": "gemini-test",
        },
    }
    service.translate_verses.assert_not_awaited()


@pytest.mark.parametrize("source_title", [None, "", "   "])
async def test_heading_without_source_title_completes_without_generation(
    db_session, make_job, payload, context, service, api, source_title
):
    context["sectionHeading"]["sourceTitle"] = source_title
    job = await make_job(payload=payload)
    await process_job(db_session, job, service)
    await db_session.refresh(job)
    assert job.status == "completed"
    assert len(api) == 1
    service.translate_heading.assert_not_awaited()
    service.translate_verses.assert_not_awaited()


@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_null_section_heading_is_a_noop(
    db_session, make_job, payload, context, service, api, missing
):
    if missing:
        context.pop("sectionHeading")
    else:
        context["sectionHeading"] = None
    job = await make_job(payload=payload)
    await process_job(db_session, job, service)
    await db_session.refresh(job)
    assert job.status == "completed"
    assert len(api) == 1
    service.translate_heading.assert_not_awaited()
    service.translate_verses.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"pericopeNumber": "other"},
        {"pericopeSetId": 8},
        {"bibleTextId": 50},
        {"bibleTextId": -1},
        {"bibleTextId": "42"},
        {"sourceTitle": 42},
    ],
)
async def test_invalid_or_mismatched_heading_context_fails_without_retries(
    db_session, make_job, payload, context, service, api, changes
):
    context["sectionHeading"].update(changes)
    job = await make_job(payload=payload)
    await process_job(db_session, job, service)
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.retry_count == 0
    assert len(api) == 1
    service.translate_heading.assert_not_awaited()
    service.translate_verses.assert_not_awaited()


async def test_heading_generation_errors_use_existing_job_retries(
    db_session, make_job, payload, service, api
):
    service.translate_heading.side_effect = ValueError("Invalid heading response")
    job = await make_job(payload=payload)
    await process_job(db_session, job, service)
    await db_session.refresh(job)
    assert job.status == "queued"
    assert job.retry_count == 1
    assert "Invalid heading response" in job.error_message
    assert len(api) == 1


async def test_verse_job_keeps_existing_context_and_results_contract(
    db_session, make_job, payload, service, api
):
    payload.pop("pericopeNumber")
    payload.pop("pericopeSetId")
    service.translate_verses.return_value = TranslationResult.model_validate(
        {
            "translations": [
                {"verse_id": "MAT_14_13", "target_text": "La multitud lo siguió."}
            ]
        }
    )
    job = await make_job(payload=payload)
    await process_job(db_session, job, service)
    await db_session.refresh(job)
    assert job.status == "completed"
    assert api[0][1]["json"] == payload
    assert api[1][1]["json"] == {
        "items": [
            {
                "bibleTextId": 42,
                "projectUnitId": 1,
                "suggestedText": "La multitud lo siguió.",
                "modelInfo": "gemini-test",
            }
        ]
    }
    service.translate_heading.assert_not_awaited()
    service.translate_verses.assert_awaited_once()
