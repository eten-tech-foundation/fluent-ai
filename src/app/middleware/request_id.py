"""
middleware/request_id.py — Middleware that assigns a unique ID to every request.

Behaviour:
  1. Reads X-Request-ID header (preferred), then X-Correlation-ID, then generates
     a fresh UUID4 when neither is present.
  2. Stores the resolved ID in request.state.request_id so any downstream handler
     or exception handler can retrieve it without re-parsing headers.
  3. Adds X-Request-ID to every response header, including error responses that
     bypass the normal response pipeline.

Usage (in main.py):
    from app.middleware.request_id import RequestIDMiddleware
    app.add_middleware(RequestIDMiddleware)
"""

import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every inbound request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Prefer an ID already set by an upstream proxy or client.
        request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or str(uuid.uuid4())
        )

        # Store on request state so routers and exception handlers can access it.
        request.state.request_id = request_id

        response: Response = await call_next(request)

        # Echo the resolved ID back so clients can correlate logs.
        response.headers["X-Request-ID"] = request_id

        return response
