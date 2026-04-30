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
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_response(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        ),
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
    app.add_exception_handler(ValidationException, _handle_validation_exception)
    app.add_exception_handler(AuthenticationException, _handle_authentication_exception)
    app.add_exception_handler(AuthorizationException, _handle_authorization_exception)
    app.add_exception_handler(NotFoundException, _handle_not_found_exception)
    app.add_exception_handler(ConflictException, _handle_conflict_exception)
    app.add_exception_handler(DatabaseException, _handle_database_exception)
    app.add_exception_handler(
        ExternalServiceException, _handle_external_service_exception
    )
    # Base class catch-all (must come after all subclasses)
    app.add_exception_handler(FluentAIException, _handle_fluent_ai_exception)

    # FastAPI / Starlette built-ins
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(HTTPException, _handle_http_exception)

    # Absolute catch-all
    app.add_exception_handler(Exception, _handle_unhandled_exception)
