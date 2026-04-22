from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.internal.models import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyInfo
from app.security.auth import require_admin, require_api_key
from app.services.api_key import (
    create_api_key,
    get_api_key_by_id,
    list_api_keys,
    revoke_api_key,
    update_api_key,
)

router = APIRouter(tags=["api-keys"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApiKeyUpdate(BaseModel):
    name: str | None = None
    permissions: list[str] | None = None
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/admin/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key",
)
async def create_key(
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> ApiKeyCreated:
    return await create_api_key(db, payload)


@router.get(
    "/admin/api-keys",
    response_model=list[ApiKeyInfo],
    summary="List all API keys",
)
async def list_keys(
    db: AsyncSession = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> list[ApiKey]:
    return await list_api_keys(db)


@router.patch(
    "/admin/api-keys/{key_id}",
    response_model=ApiKeyInfo,
    summary="Update an API key's name, permissions, or expiry",
)
async def patch_key(
    key_id: uuid.UUID,
    payload: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> ApiKey:
    record = await update_api_key(db, key_id, payload)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    return record


@router.delete(
    "/admin/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: ApiKey = Depends(require_admin),
) -> None:
    record = await revoke_api_key(db, key_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")


# ---------------------------------------------------------------------------
# Key-holder endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/api-keys/me",
    response_model=ApiKeyInfo,
    summary="Get current API key info",
)
async def get_my_key(
    api_key: ApiKey = Depends(require_api_key),
) -> ApiKey:
    return api_key