"""
tests/test_error_handlers.py — Tests for global exception handlers, error envelope shape,
and request-ID middleware.

Uses a minimal FastAPI app (not the main app) so routes can raise each exception
type in isolation without side effects on the real API.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from app.errors.codes import ErrorCode
from app.errors.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    NotFoundException,
    ValidationException,
)
from app.errors.handlers import register_exception_handlers
from app.middleware.request_id import RequestIDMiddleware


# ---------------------------------------------------------------------------
# Minimal test app
# ---------------------------------------------------------------------------

def _make_test_app() -> FastAPI:
    _app = FastAPI()
    _app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(_app)

    @_app.get("/raise/validation")
    async def _raise_validation():
        raise ValidationException(message="bad field", details={"field": "name"})

    @_app.get("/raise/authentication")
    async def _raise_authentication():
        raise AuthenticationException(message="who are you", code=ErrorCode.AUTHENTICATION_REQUIRED)

    @_app.get("/raise/authorization")
    async def _raise_authorization():
        raise AuthorizationException(message="not allowed", code=ErrorCode.AUTHORIZATION_DENIED)

    @_app.get("/raise/not-found")
    async def _raise_not_found():
        raise NotFoundException(message="thing 99 not found", details={"id": 99})

    @_app.get("/raise/conflict")
    async def _raise_conflict():
        raise ConflictException(message="already exists")

    @_app.get("/raise/database")
    async def _raise_database():
        raise DatabaseException(message="query failed", details={"table": "projects"})

    @_app.get("/raise/external")
    async def _raise_external():
        raise ExternalServiceException(message="upstream unavailable")

    @_app.get("/raise/http")
    async def _raise_http():
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @_app.get("/raise/unhandled")
    async def _raise_unhandled():
        raise RuntimeError("raw internal error — must not reach client")

    @_app.get("/raise/request-validation")
    async def _raise_request_validation(required_int: int):
        return {"value": required_int}

    return _app


@pytest.fixture(scope="module")
def ec():
    """Error-handler test client. raise_server_exceptions=False lets 5xx responses come back as responses."""
    with TestClient(_make_test_app(), raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(response) -> dict:
    """Extract the inner error dict from an ErrorResponse envelope."""
    body = response.json()
    assert "error" in body, f"Response has no 'error' key: {body}"
    return body["error"]


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------

class TestErrorEnvelope:
    """Every error response wraps its payload in the standard envelope."""

    def test_envelope_has_required_fields(self, ec):
        r = ec.get("/raise/not-found")
        err = _error(r)
        assert "code" in err
        assert "message" in err
        assert "request_id" in err
        assert "timestamp" in err

    def test_request_id_is_non_empty(self, ec):
        r = ec.get("/raise/not-found")
        assert _error(r)["request_id"] != ""

    def test_timestamp_is_iso8601(self, ec):
        from datetime import datetime
        r = ec.get("/raise/not-found")
        ts = _error(r)["timestamp"]
        datetime.fromisoformat(ts)  # raises if not valid ISO-8601


# ---------------------------------------------------------------------------
# Exception type → status code + error code
# ---------------------------------------------------------------------------

class TestExceptionHandlers:
    def test_validation_exception_returns_400(self, ec):
        r = ec.get("/raise/validation")
        assert r.status_code == 400
        assert _error(r)["code"] == ErrorCode.VALIDATION_ERROR

    def test_authentication_exception_returns_401(self, ec):
        r = ec.get("/raise/authentication")
        assert r.status_code == 401
        assert _error(r)["code"] == ErrorCode.AUTHENTICATION_REQUIRED

    def test_authorization_exception_returns_403(self, ec):
        r = ec.get("/raise/authorization")
        assert r.status_code == 403
        assert _error(r)["code"] == ErrorCode.AUTHORIZATION_DENIED

    def test_not_found_exception_returns_404(self, ec):
        r = ec.get("/raise/not-found")
        assert r.status_code == 404
        assert _error(r)["code"] == ErrorCode.RESOURCE_NOT_FOUND

    def test_conflict_exception_returns_409(self, ec):
        r = ec.get("/raise/conflict")
        assert r.status_code == 409
        assert _error(r)["code"] == ErrorCode.RESOURCE_CONFLICT

    def test_database_exception_returns_500(self, ec):
        r = ec.get("/raise/database")
        assert r.status_code == 500
        assert _error(r)["code"] == ErrorCode.DATABASE_ERROR

    def test_external_service_exception_returns_502(self, ec):
        r = ec.get("/raise/external")
        assert r.status_code == 502
        assert _error(r)["code"] == ErrorCode.EXTERNAL_SERVICE_ERROR

    def test_http_exception_is_wrapped_in_envelope(self, ec):
        r = ec.get("/raise/http")
        assert r.status_code == 418
        assert "error" in r.json()

    def test_unhandled_exception_returns_500(self, ec):
        r = ec.get("/raise/unhandled")
        assert r.status_code == 500
        assert _error(r)["code"] == ErrorCode.INTERNAL_SERVER_ERROR

    def test_request_validation_error_returns_422(self, ec):
        r = ec.get("/raise/request-validation", params={"required_int": "not-a-number"})
        assert r.status_code == 422
        assert _error(r)["code"] == ErrorCode.VALIDATION_ERROR


# ---------------------------------------------------------------------------
# Security properties
# ---------------------------------------------------------------------------

class TestSecurityProperties:
    def test_database_exception_details_suppressed(self, ec):
        """DB details (table names, query info) must never be returned to clients."""
        r = ec.get("/raise/database")
        assert _error(r)["details"] is None

    def test_unhandled_exception_message_sanitized(self, ec):
        """Raw exception messages must not be exposed (show_stack_traces defaults to False)."""
        r = ec.get("/raise/unhandled")
        assert "raw internal error" not in _error(r)["message"]

    def test_validation_details_are_preserved(self, ec):
        """Non-sensitive details (field names) should be forwarded to help the caller."""
        r = ec.get("/raise/validation")
        assert _error(r)["details"] is not None

    def test_not_found_details_preserved(self, ec):
        r = ec.get("/raise/not-found")
        assert _error(r)["details"] == {"id": 99}

    def test_request_validation_details_contain_field_errors(self, ec):
        r = ec.get("/raise/request-validation", params={"required_int": "not-a-number"})
        details = _error(r)["details"]
        assert isinstance(details, list)
        assert len(details) > 0
        assert "field" in details[0]
        assert "issue" in details[0]


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------

class TestRequestID:
    def test_x_request_id_header_present_on_error(self, ec):
        r = ec.get("/raise/not-found")
        assert "x-request-id" in r.headers

    def test_x_request_id_matches_envelope_request_id(self, ec):
        r = ec.get("/raise/not-found")
        assert r.headers["x-request-id"] == _error(r)["request_id"]

    def test_custom_request_id_is_preserved(self, ec):
        r = ec.get("/raise/not-found", headers={"X-Request-ID": "my-trace-id"})
        assert r.headers["x-request-id"] == "my-trace-id"
        assert _error(r)["request_id"] == "my-trace-id"
