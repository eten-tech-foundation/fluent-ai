"""models/api_key.py — ORM model for ai.api_keys.

Schema: ai (owned by this service, Alembic-managed).
Access: full DML — this service creates, updates, and revokes API keys.
Base:   OwnedBase (from app.db.base).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import OwnedBase


class ApiKey(OwnedBase):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(owner_user_id, owner_org_id) = 1",
            name="ck_api_keys_single_owner",
        ),
        {"schema": "ai"},
    )

    id: Column = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash: Column = Column(Text, nullable=False, unique=True)
    name: Column = Column(String(255), nullable=False)
    permissions: Column = Column(ARRAY(Text), nullable=False, server_default="{}")
    is_active: Column = Column(Boolean, nullable=False, default=True)
    owner_user_id: Column = Column(Integer, nullable=True)
    owner_org_id: Column = Column(Integer, nullable=True)
    created_at: Column = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    expires_at: Column = Column(DateTime(timezone=True), nullable=True)
