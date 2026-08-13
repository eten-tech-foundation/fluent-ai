"""
errors/codes.py — String constants for all API error codes.

Group errors by domain so callers can reference a single constant
(e.g. ErrorCode.RESOURCE_NOT_FOUND) rather than raw strings.
"""


class ErrorCode:
    """Namespace for all error code string constants."""

    # ------------------------------------------------------------------ #
    # Validation (400, 422)
    # ------------------------------------------------------------------ #
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_FIELD = "INVALID_FIELD"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"

    # ------------------------------------------------------------------ #
    # Authentication (401)
    # ------------------------------------------------------------------ #
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"

    # ------------------------------------------------------------------ #
    # Authorization (403)
    # ------------------------------------------------------------------ #
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"

    # ------------------------------------------------------------------ #
    # Not Found (404)
    # ------------------------------------------------------------------ #
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

    # ------------------------------------------------------------------ #
    # Conflict (409)
    # ------------------------------------------------------------------ #
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"

    # ------------------------------------------------------------------ #
    # Database (500)
    # ------------------------------------------------------------------ #
    DATABASE_ERROR = "DATABASE_ERROR"
    DATABASE_CONNECTION_ERROR = "DATABASE_CONNECTION_ERROR"
    DATABASE_CONSTRAINT_VIOLATION = "DATABASE_CONSTRAINT_VIOLATION"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"

    # ------------------------------------------------------------------ #
    # External services (502)
    # ------------------------------------------------------------------ #
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    EXTERNAL_SERVICE_TIMEOUT = "EXTERNAL_SERVICE_TIMEOUT"
    EXTERNAL_SERVICE_UNAVAILABLE = "EXTERNAL_SERVICE_UNAVAILABLE"

    # ------------------------------------------------------------------ #
    # Tool execution (502) — in-process tool failures, distinct from
    # remote HTTP upstream failures (EXTERNAL_SERVICE_*).
    # ------------------------------------------------------------------ #
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"

    # ------------------------------------------------------------------ #
    # Service unavailable (503)
    # ------------------------------------------------------------------ #
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    # ------------------------------------------------------------------ #
    # Source TTS (400, 502, 503)
    #
    # These codes are part of the TTS contract, not decoration: fluent-web
    # branches on the HTTP status and an operator reads the code, so
    # "text too long" must stay distinguishable from "malformed request"
    # (source-tts proposal §7.1).
    # ------------------------------------------------------------------ #
    TTS_INVALID_REQUEST = "TTS_INVALID_REQUEST"
    TTS_TEXT_TOO_LONG = "TTS_TEXT_TOO_LONG"
    TTS_STORAGE_NOT_CONFIGURED = "TTS_STORAGE_NOT_CONFIGURED"
    TTS_STORAGE_ERROR = "TTS_STORAGE_ERROR"
    # get-audio (§7.2): the waterfall's own answers.
    #
    # TTS_ARTIFACT_NOT_FOUND is the 404 rung and is *routine* — it means no
    # request sidecar was ever written for this hash, and the client heals by
    # re-calling generate and retrying (§7.2 rung 4), so it must stay
    # distinguishable from a storage fault.
    #
    # TTS_BUSY is the admission refusal (§9.2) and is the only code that
    # travels with a Retry-After header; a client that sees it waits and
    # retries rather than reporting a failure.
    TTS_ARTIFACT_NOT_FOUND = "TTS_ARTIFACT_NOT_FOUND"
    TTS_BUSY = "TTS_BUSY"
    TTS_PROVIDER_UNAVAILABLE = "TTS_PROVIDER_UNAVAILABLE"

    # ------------------------------------------------------------------ #
    # Internal (500)
    # ------------------------------------------------------------------ #
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
