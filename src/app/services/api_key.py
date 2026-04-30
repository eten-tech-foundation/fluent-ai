from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.internal.models import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyUpdate

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
    # if payload.owner_user_id is None and payload.owner_org_id is None:
    #     raise ValueError("Either owner_user_id or owner_org_id must be provided.")
    # if payload.owner_user_id is not None and payload.owner_org_id is not None:
    #     raise ValueError("Provide either owner_user_id or owner_org_id, not both.")

    raw_key = generate_raw_key()
    key_hash = hash_key(raw_key)

    record = ApiKey(
        id=uuid.uuid4(),
        key_hash=key_hash,
        name=payload.name,
        permissions=payload.permissions,
        is_active=True,
        owner_user_id=payload.owner_user_id,
        owner_org_id=payload.owner_org_id,
        created_at=datetime.now(timezone.utc),
        expires_at=payload.expires_at,
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
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    return result.scalar_one_or_none()


async def get_api_key_by_id(db: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    )
    return result.scalar_one_or_none()


async def list_api_keys(db: AsyncSession) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def update_api_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    payload: ApiKeyUpdate,
) -> ApiKey | None:
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
    return record


async def revoke_api_key(db: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    record = await get_api_key_by_id(db, key_id)
    if record:
        record.is_active = False
        await db.commit()
        await db.refresh(record)
    return record