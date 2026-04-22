# models/api_key.py — ORM model for ai.api_keys.
#
# This is the future home of the ApiKey model, once it is extracted from
# app/internal/models.py. Until that migration happens, the live model
# is at app/internal/models.py:ApiKey.
#
# Schema: ai (owned by this service, Alembic-managed)
# Access: full DML — this service creates, updates, and revokes API keys.
# Base: OwnedBase (from app.db.base)
#
# Example contents when implemented:
#
#   from __future__ import annotations
#   import uuid
#   from datetime import datetime
#
#   from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, String, Text, ARRAY
#   from sqlalchemy.dialects.postgresql import UUID
#
#   from app.db.base import OwnedBase
#
#   class ApiKey(OwnedBase):
#       __tablename__ = "api_keys"
#       __table_args__ = (
#           CheckConstraint(
#               "num_nonnulls(owner_user_id, owner_org_id) = 1",
#               name="ck_api_keys_single_owner",
#           ),
#           {"schema": "ai"},
#       )
#
#       id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#       key_hash = Column(Text, nullable=False, unique=True)
#       name = Column(String(255), nullable=False)
#       permissions = Column(ARRAY(Text), nullable=False, server_default="{}")
#       is_active = Column(Boolean, nullable=False, default=True)
#       owner_user_id = Column(UUID(as_uuid=True), nullable=True)
#       owner_org_id = Column(UUID(as_uuid=True), nullable=True)
#       created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
#       expires_at = Column(DateTime(timezone=True), nullable=True)
