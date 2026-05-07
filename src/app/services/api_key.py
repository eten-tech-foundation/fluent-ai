from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.internal.models import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyInfo, ApiKeyUpdate

_KEY_PREFIX = "fai"
_KEY_BYTES = 32


def generate_raw_key() -> str:
    token = secrets.token_urlsafe(_KEY_BYTES)
    return f"{_KEY_PREFIX}_{token}"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def create_api_key(
    db: AsyncSession,
    payload: ApiKeyCreate,
) -> ApiKeyCreated:
    raw_key = generate_raw_key()
    key_hash = hash_key(raw_key)
    now = datetime.now(timezone.utc)

    if payload.expires_at is not None:
        expires_at = payload.expires_at
    elif (days := get_settings().api_key_default_expiry_days) is not None:
        expires_at = now + timedelta(days=days)
    else:
        expires_at = None

    record = ApiKey(
        id=uuid.uuid4(),
        key_hash=key_hash,
        name=payload.name,
        permissions=payload.permissions,
        is_active=True,
        owner_user_id=payload.owner_user_id,
        owner_org_id=payload.owner_org_id,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        permissions=record.permissions,
        raw_key=raw_key,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


async def get_api_key_by_hash(db: AsyncSession, raw_key: str) -> ApiKey | None:
    key_hash = hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_api_key_by_id(db: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    )
    return result.scalar_one_or_none()


async def list_api_keys(db: AsyncSession) -> list[ApiKeyInfo]:
    result = await db.execute(
        select(ApiKey).order_by(ApiKey.created_at.desc())
    )
    return [ApiKeyInfo.model_validate(r) for r in result.scalars().all()]


async def update_api_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    payload: ApiKeyUpdate,
) -> ApiKeyInfo | None:
    record = await get_api_key_by_id(db, key_id)
    if record is None:
        return None

    if payload.name is not None:
        record.name = payload.name
    if payload.permissions is not None:
        record.permissions = payload.permissions
    if payload.expires_at is not None:
        record.expires_at = payload.expires_at

    await db.commit()
    await db.refresh(record)
    return ApiKeyInfo.model_validate(record)


async def revoke_api_key(db: AsyncSession, key_id: uuid.UUID) -> ApiKeyInfo | None:
    record = await get_api_key_by_id(db, key_id)
    if record is None:
        return None
    record.is_active = False
    await db.commit()
    await db.refresh(record)
    return ApiKeyInfo.model_validate(record)