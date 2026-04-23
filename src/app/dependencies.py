"""
dependencies.py — Shared FastAPI dependency functions.
"""
from fastapi import Header

from app.errors.codes import ErrorCode
from app.errors.exceptions import AuthenticationException


async def get_token_header(x_token: str = Header(...)) -> None:
    """Validate the X-Token header required by the items router."""
    if x_token != "fake-super-secret-token":
        raise AuthenticationException(
            message="Invalid or missing X-Token header.",
            code=ErrorCode.TOKEN_INVALID,
            details={"header": "X-Token"},
        )


async def get_query_token(token: str | None = None) -> str:
    """Validate a token passed as a query parameter."""
    if not token:
        raise AuthenticationException(
            message="A token query parameter is required.",
            code=ErrorCode.AUTHENTICATION_REQUIRED,
        )
    return token
