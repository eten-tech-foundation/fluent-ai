"""
tests/api/v1/test_greek_room.py — endpoint tests for /tools/greek-room/

Three tests covering the integration surface:
  1. Happy-path: real greek-room library runs against a small canned corpus.
     One verse with a legitimate duplicate ("Truly, truly, ..."), one with
     a suspicious duplicate ("In in the beginning."), one clean verse.
  2. Tool failure → 502 with code TOOL_EXECUTION_ERROR (service override
     stub raises so the route's ToolExecutionException path is exercised).
  3. Missing API key → 401 (no header, no override).
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.dependencies import get_repeated_words_service, require_api_key
from app.errors.codes import ErrorCode
from app.errors.exceptions import ToolExecutionException
from app.main import app
from app.models.api_key import ApiKey
from app.schemas.greek_room import RepeatedWordsRequest, RepeatedWordsResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_api_key():
    record = ApiKey()
    record.id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    record.key_hash = "irrelevant"
    record.name = "test-key"
    record.permissions = []
    record.is_active = True
    record.owner_user_id = 42
    record.owner_org_id = None
    record.created_at = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
    record.expires_at = None
    return record


@pytest.fixture
def authed_client(client, fake_api_key):
    """Client with require_api_key overridden to return a fake non-admin key."""
    app.dependency_overrides[require_api_key] = lambda: fake_api_key
    yield client
    app.dependency_overrides.pop(require_api_key, None)


# ---------------------------------------------------------------------------
# Shared request payload
# ---------------------------------------------------------------------------


SAMPLE_PAYLOAD = {
    "lang_code": "eng",
    "lang_name": "English",
    "project_id": "test-project",
    "project_name": "Test Project",
    "verses": [
        {"snt_id": "GEN 1:1", "text": "In in the beginning God created the heavens."},
        {"snt_id": "JHN 3:3", "text": "Truly, truly, I say unto thee."},
        {"snt_id": "PSA 23:1", "text": "The Lord is my shepherd."},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRepeatedWordsEndpoint:
    def test_happy_path_real_greek_room(self, authed_client):
        """End-to-end against the real greek-room library.

        Two findings are expected:
          - "in in" in GEN 1:1, legitimate=False, severity=0.5
          - "truly truly" (or similar) in JHN 3:3, legitimate=True, severity=0.1
        PSA 23:1 has no duplicates and should produce no findings.
        """
        response = authed_client.post(
            "/tools/greek-room/repeated-words", json=SAMPLE_PAYLOAD
        )

        assert response.status_code == 200, response.text
        body = response.json()

        # Envelope shape
        assert body["status"] == "completed"
        assert body["tool"] == "greek_room.repeated_words"
        assert body["error"] is None
        assert body["job_id"]
        assert body["created_at"]
        assert body["completed_at"]

        # Result shape
        result = body["result"]
        assert result is not None
        assert result["lang_code"] == "eng"
        assert result["provider"] == "GreekRoom"
        assert result["check"] == "RepeatedWords"

        findings = result["findings"]
        assert len(findings) == 2, f"expected 2 findings, got {findings!r}"

        legitimate = [f for f in findings if f["legitimate"]]
        suspicious = [f for f in findings if not f["legitimate"]]
        assert len(legitimate) == 1
        assert len(suspicious) == 1

        # Suspicious finding is the "in in" in GEN 1:1
        sus = suspicious[0]
        assert sus["snt_id"] == "GEN 1:1"
        assert sus["severity"] == 0.5

        # Legitimate finding is in JHN 3:3
        leg = legitimate[0]
        assert leg["snt_id"] == "JHN 3:3"
        assert leg["severity"] == 0.1

        # Summary matches findings
        summary = result["summary"]
        assert summary["total_findings"] == 2
        assert summary["legitimate_count"] == 1
        assert summary["verse_count"] == 3

    def test_tool_failure_returns_502(self, authed_client):
        """When the service's execute() raises ToolExecutionException,
        the global exception handler should surface it as a 502 with the
        TOOL_EXECUTION_ERROR wire code."""

        class FailingService:
            name = "greek_room.repeated_words"
            request_schema = RepeatedWordsRequest
            response_schema = RepeatedWordsResult

            async def execute(self, request: RepeatedWordsRequest) -> RepeatedWordsResult:
                raise ToolExecutionException(
                    tool=self.name,
                    message="simulated upstream failure",
                )

        app.dependency_overrides[get_repeated_words_service] = lambda: FailingService()
        try:
            response = authed_client.post(
                "/tools/greek-room/repeated-words", json=SAMPLE_PAYLOAD
            )
        finally:
            app.dependency_overrides.pop(get_repeated_words_service, None)

        assert response.status_code == 502, response.text
        body = response.json()
        assert body["error"]["code"] == ErrorCode.TOOL_EXECUTION_ERROR
        assert body["error"]["details"]["tool"] == "greek_room.repeated_words"

    def test_missing_api_key_returns_401(self, client):
        """No X-API-Key header and no dep override → 401 from require_api_key."""
        response = client.post(
            "/tools/greek-room/repeated-words", json=SAMPLE_PAYLOAD
        )
        assert response.status_code == 401
