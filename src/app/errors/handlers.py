"""
errors/handlers.py — Global exception handlers for the Fluent AI API.

All handlers follow the same contract:
  1. Extract request_id from request.state (falls back to "unknown").
  2. Log the exception via log_exception().
  3. Return a JSONResponse with the standard ErrorResponse envelope.

Registration:
    Call register_exception_handlers(app) once in main.py, after the app
    object is created. This keeps main.py clean and avoids circular imports.

Covered exception types:
  - Each concrete FluentAIException subclass (for precise HTTP status codes)
  - FluentAIException base (catch-all for any unregistered subclass)
  - RequestValidationError  (FastAPI / Pydantic 422 body validation errors)
  - HTTPException           (FastAPI native — wrapped into ErrorResponse format)
  - Exception               (catch-all 500; message sanitized in production)
"""

import asyncio
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.errors.codes import ErrorCode
from app.errors.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    FluentAIException,
    NotFoundException,
    ServiceUnavailableException,
    ValidationException,
)
from app.errors.logging import get_logger, log_exception
from app.errors.schemas import build_error_response

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _get_request_id(request: Request) -> str:
    """Extract the request ID stored by RequestIDMiddleware."""
    return getattr(request.state, "request_id", "unknown")


def _json_error(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details=None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_response(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        ),
        headers=headers,
    )


# --------------------------------------------------------------------------- #
# Handlers — custom FluentAIException subclasses
# --------------------------------------------------------------------------- #


async def _handle_validation_exception(
    request: Request, exc: ValidationException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code, details=exc.details)
    return _json_error(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def _handle_authentication_exception(
    request: Request, exc: AuthenticationException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code, level=logging.WARNING)

    # Rate limit error endpoints to prevent abuse (crude tarpit for auth failures)
    await asyncio.sleep(0.5)

    return _json_error(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def _handle_authorization_exception(
    request: Request, exc: AuthorizationException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code, level=logging.WARNING)
    return _json_error(
        status_code=status.HTTP_403_FORBIDDEN,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def _handle_not_found_exception(
    request: Request, exc: NotFoundException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code, level=logging.INFO)
    return _json_error(
        status_code=status.HTTP_404_NOT_FOUND,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def _handle_conflict_exception(
    request: Request, exc: ConflictException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code, level=logging.WARNING)
    return _json_error(
        status_code=status.HTTP_409_CONFLICT,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def _handle_database_exception(
    request: Request, exc: DatabaseException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code)
    return _json_error(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        # Never expose raw DB details externally.
        details=None,
    )


async def _handle_external_service_exception(
    request: Request, exc: ExternalServiceException
) -> JSONResponse:
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code)
    return _json_error(
        status_code=status.HTTP_502_BAD_GATEWAY,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def _handle_service_unavailable_exception(
    request: Request, exc: ServiceUnavailableException
) -> JSONResponse:
    """503 responses, and the only place a `Retry-After` header is emitted.

    This handler exists for the header alone — `status_code` already travelled
    correctly through the FluentAIException catch-all, which builds the JSON
    envelope and sets no headers whatsoever.

    Why not the two obvious alternatives, both of which fail quietly here:

    * `raise HTTPException(headers=...)` — `_handle_http_exception` below now
      forwards headers, but its status→code table has no 503 entry, so a TTS
      admission refusal would answer `INTERNAL_SERVER_ERROR` instead of
      `TTS_BUSY` and the client would stop distinguishing "wait and retry"
      from "something broke".
    * returning a `JSONResponse` from the route — the admission gate lives
      several layers below the endpoint (in the generation heap), so the route
      would have to learn about it just to attach one header, and the error
      envelope would get a second construction site.

    Raising instead keeps the refusal where the decision is made, which is what
    makes "`503` + `Retry-After` **before any body bytes**" (§9.2, §12.3) true
    by construction: the exception is raised while resolving the request, long
    before a streaming response object exists.
    """
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code, level=logging.WARNING)
    headers = (
        {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    )
    return _json_error(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
        headers=headers,
    )


async def _handle_fluent_ai_exception(
    request: Request, exc: FluentAIException
) -> JSONResponse:
    """Catch-all for any FluentAIException subclass not explicitly registered."""
    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=exc.code)
    return _json_error(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


# --------------------------------------------------------------------------- #
# Handlers — FastAPI / Starlette built-in exceptions
# --------------------------------------------------------------------------- #


async def _handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors raised by FastAPI on request parsing.

    Converts the list of error dicts into a user-friendly details structure
    and returns 422 Unprocessable Entity.
    """
    request_id = _get_request_id(request)

    # Flatten Pydantic's error list into a simpler structure.
    field_errors = [
        {
            "field": " → ".join(str(loc) for loc in err["loc"] if loc != "body"),
            "issue": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]

    log_exception(
        logger,
        request,
        exc,
        error_code=ErrorCode.VALIDATION_ERROR,
        details=field_errors,
        level=logging.WARNING,
    )

    return _json_error(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=ErrorCode.VALIDATION_ERROR,
        message="Request validation failed. Check the details for field-level errors.",
        request_id=request_id,
        details=field_errors,
    )


async def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Wrap FastAPI's native HTTPException into the ErrorResponse envelope.

    Preserves the original status code and maps it to a sensible error code.
    """
    request_id = _get_request_id(request)

    # Map common HTTP status codes to error code constants.
    _status_to_code: dict[int, str] = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.AUTHENTICATION_REQUIRED,
        403: ErrorCode.AUTHORIZATION_DENIED,
        404: ErrorCode.RESOURCE_NOT_FOUND,
        405: ErrorCode.VALIDATION_ERROR,
        409: ErrorCode.RESOURCE_CONFLICT,
        422: ErrorCode.VALIDATION_ERROR,
        500: ErrorCode.INTERNAL_SERVER_ERROR,
        502: ErrorCode.EXTERNAL_SERVICE_ERROR,
    }
    code = _status_to_code.get(exc.status_code, ErrorCode.INTERNAL_SERVER_ERROR)

    log_exception(
        logger,
        request,
        exc,
        error_code=code,
        level=logging.WARNING if exc.status_code < 500 else logging.ERROR,
    )

    return _json_error(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
        request_id=request_id,
        # Forwarded rather than dropped: `HTTPException(headers=...)` is the
        # documented way to attach `WWW-Authenticate`, `Retry-After` and
        # friends, and silently discarding them makes a route look correct
        # while the header the client depends on never arrives.
        headers=getattr(exc, "headers", None),
    )


async def _handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for any exception not matched by a more specific handler.

    In production the message is sanitized so internal details are never leaked.
    """
    from app.config import get_settings

    request_id = _get_request_id(request)
    log_exception(logger, request, exc, error_code=ErrorCode.INTERNAL_SERVER_ERROR)

    settings = get_settings()
    message = (
        str(exc)
        if settings.show_stack_traces
        else "An unexpected error occurred. Please try again later."
    )

    return _json_error(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ErrorCode.INTERNAL_SERVER_ERROR,
        message=message,
        request_id=request_id,
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers on the FastAPI application instance.

    Call this once in main.py immediately after creating the app object.
    The order matters: more-specific subclasses must be registered before
    the FluentAIException base-class handler.
    """
    # Custom hierarchy — most specific first
    app.add_exception_handler(ValidationException, _handle_validation_exception)  # type: ignore[arg-type]
    app.add_exception_handler(AuthenticationException, _handle_authentication_exception)  # type: ignore[arg-type]
    app.add_exception_handler(AuthorizationException, _handle_authorization_exception)  # type: ignore[arg-type]
    app.add_exception_handler(NotFoundException, _handle_not_found_exception)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictException, _handle_conflict_exception)  # type: ignore[arg-type]
    app.add_exception_handler(DatabaseException, _handle_database_exception)  # type: ignore[arg-type]
    app.add_exception_handler(
        ExternalServiceException,
        _handle_external_service_exception,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        ServiceUnavailableException,
        _handle_service_unavailable_exception,  # type: ignore[arg-type]
    )
    # Base class catch-all (must come after all subclasses)
    app.add_exception_handler(FluentAIException, _handle_fluent_ai_exception)  # type: ignore[arg-type]

    # FastAPI / Starlette built-ins
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _handle_http_exception)  # type: ignore[arg-type]

    # Absolute catch-all
    app.add_exception_handler(Exception, _handle_unhandled_exception)
