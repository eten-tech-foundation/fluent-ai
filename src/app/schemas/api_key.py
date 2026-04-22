# src/app/schemas/api_key.py
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)
    owner_user_id: uuid.UUID | None = None
    owner_org_id: uuid.UUID | None = None
    expires_at: datetime | None = None  # None = use config default or never


class ApiKeyCreated(BaseModel):
    """Returned once at creation — raw key is never stored and cannot be retrieved again."""
    id: uuid.UUID
    name: str
    permissions: list[str]
    raw_key: str  # shown to caller exactly once
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyInfo(BaseModel):
    """Safe read model — never exposes key_hash or raw_key."""
    id: uuid.UUID
    name: str
    permissions: list[str]
    is_active: bool
    owner_user_id: uuid.UUID | None
    owner_org_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}