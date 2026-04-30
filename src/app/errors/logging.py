"""
errors/logging.py — Structured logging utilities for exception tracking.

All log entries include request_id, path, method, and error metadata.
Stack traces are only emitted when settings.show_stack_traces is True
(i.e. in development mode) so production logs never leak implementation details.

Usage:
    from app.errors.logging import get_logger, log_exception

    logger = get_logger(__name__)

    log_exception(logger, request, exc)
"""

import logging
import traceback
from typing import Any

from fastapi import Request

from app.config import get_settings

settings = get_settings()


def get_logger(name: str) -> logging.Logger:
    """
    Return a stdlib Logger for the given module name.

    Configure the root level once at import time so every logger
    in the application inherits the same level.
    """
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(name)


def _build_log_extra(
    request: Request,
    *,
    request_id: str,
    error_code: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the structured fields attached to every error log record."""
    payload: dict[str, Any] = {
        "request_id": request_id,
        "method": request.method,
        "path": str(request.url.path),
        "error_code": error_code,
    }
    if extra:
        payload.update(extra)
    return payload


def log_exception(
    logger: logging.Logger,
    request: Request,
    exc: Exception,
    *,
    error_code: str = "UNKNOWN",
    details: Any | None = None,
    level: int = logging.ERROR,
) -> None:
    """
    Emit a structured log record for an exception.

    Stack traces are included only when show_stack_traces is enabled
    (i.e. debug / development mode). In production the trace is suppressed
    to avoid leaking implementation details.
    """
    request_id: str = getattr(request.state, "request_id", "unknown")

    extra = _build_log_extra(
        request,
        request_id=request_id,
        error_code=error_code,
        extra={"details": details} if details is not None else None,
    )

    message = f"{type(exc).__name__}: {exc}"

    if settings.show_stack_traces:
        stack = traceback.format_exc()
        logger.log(level, "%s\n%s", message, stack, extra=extra)
    else:
        logger.log(level, message, extra=extra)
