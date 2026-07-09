"""
tests/api/v1/test_suggestions.py — Tests for the POST /suggestions endpoint.

Auth pattern matches tests/api/v1/test_api_keys.py: `require_api_key` is
overridden via `app.dependency_overrides` (there is no `api_key_header`
fixture anywhere in this codebase — auth is exercised via dependency
overrides, not real header values).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.constants import MAX_SUGGESTION_BATCH_SIZE
from app.dependencies import require_api_key
from app.main import app
from app.models.api_key import ApiKey

USER_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)


def _api_key_record() -> ApiKey:
    record = ApiKey()
    record.id = USER_ID
    record.key_hash = "irrelevant"
    record.name = "test-key"
    record.permissions = []
    record.is_active = True
    record.owner_user_id = 42
    record.owner_org_id = None
    record.created_at = NOW
    record.expires_at = None
    return record


@pytest.fixture
def authed_client(client):
    """Client authenticated as a valid (non-admin) API key."""
    app.dependency_overrides[require_api_key] = lambda: _api_key_record()
    yield client
    app.dependency_overrides.pop(require_api_key, None)


def _request(verse_start: int = 1) -> dict:
    return {
        "projectUnitId": 1,
        "bibleId": 1,
        "bookCode": "MAT",
        "chapterNumber": 1,
        "verseStart": verse_start,
        "verseEnd": verse_start,
    }


def test_trigger_suggestions_rejects_batch_over_max_size(authed_client):
    oversized = [_request(i) for i in range(MAX_SUGGESTION_BATCH_SIZE + 1)]
    response = authed_client.post("/suggestions", json=oversized)
    assert response.status_code == 400


def test_trigger_suggestions_accepts_batch_at_max_size(authed_client, monkeypatch):
    import app.api.v1.endpoints.suggestions as suggestions_endpoint

    monkeypatch.setattr(
        suggestions_endpoint,
        "enqueue_suggestion_jobs",
        AsyncMock(return_value={"message": "Queued 100 jobs"}),
    )
    at_max = [_request(i) for i in range(MAX_SUGGESTION_BATCH_SIZE)]
    response = authed_client.post("/suggestions", json=at_max)
    assert response.status_code == 200
