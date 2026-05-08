"""
logging/middleware.py — Request/response cycle logging.

Runs after RequestIDMiddleware (which is outermost). Reads request_id from
request.state, writes it to the ContextVar, then logs request start and
completion. All downstream log calls inherit request_id automatically.

When log_sampling_rate < 1.0, a random fraction of INFO-level request logs
are suppressed to reduce noise on high-throughput endpoints. Errors and
warnings always emit regardless of sampling rate.
"""

import random
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.logging.context import set_request_context
from app.logging.utils import get_logger

logger = get_logger(__name__)

# Read once at import time — avoids per-request settings lookup.
_sampling_rate: float = get_settings().log_sampling_rate


def _should_log_info() -> bool:
    """Return True if this INFO-level request log should be emitted."""
    return _sampling_rate >= 1.0 or random.random() < _sampling_rate


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response cycle with timing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = getattr(request.state, "request_id", "")
        correlation_id = getattr(request.state, "correlation_id", "")
        set_request_context(request_id, correlation_id)

        start = time.monotonic()
        emit_info = _should_log_info()

        if emit_info:
            client_ip = request.headers.get("X-Forwarded-For") or (
                request.client.host if request.client else "unknown"
            )
            logger.info(
                "Request started",
                method=request.method,
                path=str(request.url.path),
                client_ip=client_ip,
            )

        try:
            response = await call_next(request)
            duration_ms = round((time.monotonic() - start) * 1000, 2)

            if emit_info:
                logger.info(
                    "Request completed",
                    method=request.method,
                    path=str(request.url.path),
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
            return response
        except BaseException as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            # Errors always log, regardless of sampling rate.
            logger.error(
                "Request failed",
                method=request.method,
                path=str(request.url.path),
                duration_ms=duration_ms,
                error=type(exc).__name__,
            )
            raise
