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
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OwnedBase


class ApiKey(OwnedBase):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index(
            "idx_api_keys_key_hash",
            "key_hash",
            postgresql_where=text("is_active = true"),
        ),
        CheckConstraint(
            "num_nonnulls(owner_user_id, owner_org_id) = 1",
            name="ck_api_keys_single_owner",
        ),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
