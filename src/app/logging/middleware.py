"""
logging/middleware.py — Request/response cycle logging.

Runs after RequestIDMiddleware (which is outermost). Reads request_id from
request.state, writes it to the ContextVar, then logs request start and
completion. All downstream log calls inherit request_id automatically.
"""
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging.context import set_request_context
from app.logging.utils import get_logger

logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response cycle with timing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = getattr(request.state, "request_id", "")
        correlation_id = getattr(request.state, "correlation_id", "")
        set_request_context(request_id, correlation_id)

        start = time.monotonic()

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

            logger.info(
                "Request completed",
                method=request.method,
                path=str(request.url.path),
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "Request failed",
                method=request.method,
                path=str(request.url.path),
                duration_ms=duration_ms,
                error=type(exc).__name__,
            )
            raise
