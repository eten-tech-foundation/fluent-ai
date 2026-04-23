"""
errors/exceptions.py — Typed exception hierarchy for the Fluent AI API.

All custom exceptions extend FluentAIException, which carries:
  - code        : ErrorCode constant (becomes the wire "code" field)
  - message     : Human-readable, user-safe description
  - details     : Optional structured context (field name, constraint, etc.)
  - status_code : HTTP status code the global handler will use

Usage:
    raise NotFoundException(
        message="Project 99 not found",
        details={"project_id": 99},
    )
"""

from app.errors.codes import ErrorCode


class FluentAIException(Exception):
    """Base exception for all Fluent AI API errors."""

    status_code: int = 500
    default_code: str = ErrorCode.INTERNAL_SERVER_ERROR
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict | list | str | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details
        super().__init__(self.message)


# --------------------------------------------------------------------------- #
# 400 — Bad Request / Validation
# --------------------------------------------------------------------------- #


class ValidationException(FluentAIException):
    """Request payload or query parameter failed validation."""

    status_code = 400
    default_code = ErrorCode.VALIDATION_ERROR
    default_message = "Invalid input data."


# --------------------------------------------------------------------------- #
# 401 — Unauthenticated
# --------------------------------------------------------------------------- #


class AuthenticationException(FluentAIException):
    """Request is missing or contains invalid authentication credentials."""

    status_code = 401
    default_code = ErrorCode.AUTHENTICATION_REQUIRED
    default_message = "Authentication is required to access this resource."


# --------------------------------------------------------------------------- #
# 403 — Forbidden
# --------------------------------------------------------------------------- #


class AuthorizationException(FluentAIException):
    """Authenticated user lacks permission to perform the requested action."""

    status_code = 403
    default_code = ErrorCode.AUTHORIZATION_DENIED
    default_message = "You do not have permission to perform this action."


# --------------------------------------------------------------------------- #
# 404 — Not Found
# --------------------------------------------------------------------------- #


class NotFoundException(FluentAIException):
    """The requested resource does not exist."""

    status_code = 404
    default_code = ErrorCode.RESOURCE_NOT_FOUND
    default_message = "The requested resource was not found."


# --------------------------------------------------------------------------- #
# 409 — Conflict
# --------------------------------------------------------------------------- #


class ConflictException(FluentAIException):
    """The request conflicts with the current state of the resource."""

    status_code = 409
    default_code = ErrorCode.RESOURCE_CONFLICT
    default_message = "A conflict occurred with an existing resource."


# --------------------------------------------------------------------------- #
# 500 — Internal / Database
# --------------------------------------------------------------------------- #


class DatabaseException(FluentAIException):
    """A database operation failed in an unexpected way."""

    status_code = 500
    default_code = ErrorCode.DATABASE_ERROR
    default_message = "A database error occurred. Please try again later."


# --------------------------------------------------------------------------- #
# 502 — Bad Gateway / External Service
# --------------------------------------------------------------------------- #


class ExternalServiceException(FluentAIException):
    """An upstream AI or third-party service returned an unexpected response."""

    status_code = 502
    default_code = ErrorCode.EXTERNAL_SERVICE_ERROR
    default_message = "An external service is unavailable. Please try again later."
