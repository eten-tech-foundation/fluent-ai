from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.errors.codes import ErrorCode
from app.errors.exceptions import AuthenticationException, AuthorizationException
from app.internal.models import ApiKey
from app.services.api_key import get_api_key_by_hash

# ---------------------------------------------------------------------------
# Extractors — header preferred, query param as fallback
# auto_error=False so we can check both and give a single clean 401
# ---------------------------------------------------------------------------
_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

async def _extract_raw_key(
    request: Request,
    header_key: str | None = Security(_header_scheme),
) -> str:
    """Pull the raw key from header or query param. Prefer header."""
    raw_key = header_key or request.query_params.get("api_key")
    if not raw_key:
        raise AuthenticationException(
            message="Missing API key. Provide X-API-Key header.",
            code=ErrorCode.AUTHENTICATION_REQUIRED,
        )
    return raw_key

# ---------------------------------------------------------------------------
# Core dependency — validates key and attaches record to request state
# ---------------------------------------------------------------------------

async def require_api_key(
    request: Request,
    raw_key: str = Depends(_extract_raw_key),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """
    Validate the API key and attach it to request.state.api_key.
    Raises 401 for missing/invalid keys, 403 for inactive or expired keys.
    """
    record = await get_api_key_by_hash(db, raw_key)

    if record is None:
        raise AuthenticationException(
            message="Invalid API key.",
            code=ErrorCode.TOKEN_INVALID,
        )

    if not record.is_active:
        raise AuthorizationException(
            message="API key has been revoked.",
            code=ErrorCode.AUTHORIZATION_DENIED,
        )

    if record.expires_at and record.expires_at < datetime.now(timezone.utc):
        raise AuthorizationException(
            message="API key has expired.",
            code=ErrorCode.TOKEN_EXPIRED,
        )

    request.state.api_key = record
    return record


# ---------------------------------------------------------------------------
# Admin dependency — extends require_api_key with permission check
# ---------------------------------------------------------------------------

async def require_admin(
    api_key: ApiKey = Depends(require_api_key),
) -> ApiKey:
    """
    Requires a valid API key with 'admin' permission.
    Always runs require_api_key first.
    """
    if "admin" not in (api_key.permissions or []):
        raise AuthorizationException(
            message="Admin permission required.",
            code=ErrorCode.INSUFFICIENT_PERMISSIONS,
        )
    return api_key