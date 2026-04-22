"""
models.py — Read-only SQLAlchemy models for the AI service.

These map to tables owned by the Web API (public schema).
The AI service only has SELECT access here via role_ai_reader.
No INSERT / UPDATE / DELETE operations should be performed on these models.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ARRAY,DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB ,UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    String,
    Text,
    ARRAY,
)


class Base(DeclarativeBase):
    pass


class Project(Base):
    """
    Read-only view of public.projects.

    Owned and written to by fluent-server (web_user / role_web_data).
    The AI service reads this table via role_ai_reader.
    """

    __tablename__ = "projects"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_language: Mapped[int] = mapped_column(Integer, nullable=False)
    target_language: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organization: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'not_assigned'"))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r} status={self.status!r}>"

class ApiKey(Base):
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
    owner_user_id: Column = Column(UUID(as_uuid=True), nullable=True)
    owner_org_id: Column = Column(UUID(as_uuid=True), nullable=True)
    created_at: Column = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    expires_at: Column = Column(DateTime(timezone=True), nullable=True)        