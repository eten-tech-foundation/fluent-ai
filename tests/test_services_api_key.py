"""
tests/test_services_api_key.py — unit tests for services/api_key.py

DB and config are mocked so these run without infrastructure.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.api_key import ApiKeyCreate


def _payload(**kwargs) -> ApiKeyCreate:
    defaults = {"name": "test", "owner_user_id": 1}
    return ApiKeyCreate(**{**defaults, **kwargs})


def _make_db_record(expires_at):
    record = MagicMock()
    record.id = "00000000-0000-0000-0000-000000000001"
    record.name = "test"
    record.permissions = []
    record.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record.expires_at = expires_at
    return record


def _make_db():
    """AsyncSession mock with db.add() correctly typed as synchronous."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
class TestCreateApiKeyExpiry:
    async def test_explicit_expires_at_is_used(self):
        explicit = datetime(2027, 1, 1, tzinfo=timezone.utc)
        db = _make_db()
        record = _make_db_record(explicit)

        with patch("app.services.api_key.get_settings") as mock_settings, \
             patch("app.services.api_key.ApiKey", return_value=record):
            mock_settings.return_value.api_key_default_expiry_days = 30
            from app.services.api_key import create_api_key
            result = await create_api_key(db, _payload(expires_at=explicit))

        assert result.expires_at == explicit

    async def test_default_expiry_applied_when_expires_at_is_none(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = now + timedelta(days=30)
        db = _make_db()
        record = _make_db_record(expected)

        with patch("app.services.api_key.get_settings") as mock_settings, \
             patch("app.services.api_key.ApiKey", return_value=record), \
             patch("app.services.api_key.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_settings.return_value.api_key_default_expiry_days = 30
            from app.services.api_key import create_api_key
            result = await create_api_key(db, _payload())

        assert result.expires_at == expected

    async def test_no_expiry_when_default_is_none_and_no_payload(self):
        db = _make_db()
        record = _make_db_record(None)

        with patch("app.services.api_key.get_settings") as mock_settings, \
             patch("app.services.api_key.ApiKey", return_value=record):
            mock_settings.return_value.api_key_default_expiry_days = None
            from app.services.api_key import create_api_key
            result = await create_api_key(db, _payload())

        assert result.expires_at is None
