"""
logging/context.py — ContextVar storage for request-scoped log fields.

RequestIDMiddleware sets the context var once per request. The logging
filter chain reads it, so every log call in the request automatically
carries request_id — no manual wiring in routers or services.
"""

import contextvars

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def set_request_context(request_id: str, correlation_id: str = "") -> None:
    """Set the request-scoped IDs. Called once per request by middleware."""
    _request_id_var.set(request_id)
    _correlation_id_var.set(correlation_id)


def get_request_id() -> str:
    """Return current request ID, or empty string outside a request."""
    return _request_id_var.get()


def get_correlation_id() -> str:
    """Return current correlation ID, or empty string outside a request."""
    return _correlation_id_var.get()


def clear_request_context() -> None:
    """Reset context. Used in tests between requests."""
    _request_id_var.set("")
    _correlation_id_var.set("")
