"""
errors/logging.py — Structured logging utilities for exception tracking.

Delegates to app.logging (stdlib). Public API is unchanged — handlers.py
imports get_logger and log_exception from here with no modification needed.
"""

import logging
from typing import Any

from fastapi import Request

from app.config import get_settings
from app.logging.utils import StructuredLogger, get_logger  # re-export

__all__ = ["get_logger", "log_exception"]

# Map stdlib level integers to method names on the logger.
_LEVEL_TO_METHOD: dict[int, str] = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
    logging.CRITICAL: "critical",
}


def log_exception(
    logger: StructuredLogger,
    request: Request,
    exc: Exception,
    *,
    error_code: str = "UNKNOWN",
    details: Any | None = None,
    level: int = logging.ERROR,
) -> None:
    """
    Emit a structured log record for an exception.

    Stack traces are included only when show_stack_traces is True
    (development). In production the trace is suppressed.
    """
    settings = get_settings()
    request_id: str = getattr(request.state, "request_id", "unknown")

    extra: dict[str, Any] = {
        "request_id": request_id,
        "method": request.method,
        "path": str(request.url.path),
        "error_code": error_code,
    }
    if details is not None:
        extra["details"] = details

    message = f"{type(exc).__name__}: {exc}"
    log_fn = getattr(logger, _LEVEL_TO_METHOD.get(level, "error"))

    if settings.show_stack_traces:
        log_fn(message, exc_info=exc, **extra)
    else:
        log_fn(message, **extra)
