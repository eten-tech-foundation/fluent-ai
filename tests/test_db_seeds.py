"""Unit tests for the seed runner.

These do not touch a real database — they assert that:
  * The dev key is only seeded outside production.
  * The admin key is only seeded when settings.admin_api_key_hash is set.
  * Every seed statement uses ON CONFLICT DO NOTHING (idempotency).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.postgresql import dialect as pg_dialect
from sqlalchemy.dialects.postgresql.dml import Insert

from app.db.seeds.api_keys import (
    ADMIN_OWNER_USER_ID,
    DEV_KEY_HASH,
    PROD_KEY_NAME,
    _upsert_admin_key,
    seed_admin_api_keys,
)


def _make_settings(
    *, environment: str, admin_hash: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        environment=environment,
        is_production=(environment == "production"),
        admin_api_key_hash=admin_hash,
    )


def _execute_calls(session: AsyncMock) -> list[Insert]:
    return [call.args[0] for call in session.execute.await_args_list]


def _assert_on_conflict_do_nothing(stmt: Insert) -> None:
    assert isinstance(stmt, Insert)
    # Compile to SQL and verify the upsert is idempotent.
    sql = str(stmt.compile(dialect=pg_dialect()))
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql


async def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
    return session


@pytest.mark.asyncio
async def test_dev_key_seeded_in_development() -> None:
    session = await _make_session()
    await seed_admin_api_keys(session, _make_settings(environment="development"))

    calls = _execute_calls(session)
    assert len(calls) == 1
    _assert_on_conflict_do_nothing(calls[0])
    params = calls[0].compile(dialect=pg_dialect()).params
    assert params["key_hash"] == DEV_KEY_HASH
    assert params["owner_user_id"] == ADMIN_OWNER_USER_ID
    assert params["owner_org_id"] is None


@pytest.mark.asyncio
async def test_dev_key_skipped_in_production() -> None:
    session = await _make_session()
    await seed_admin_api_keys(session, _make_settings(environment="production"))

    assert _execute_calls(session) == []


@pytest.mark.asyncio
async def test_admin_key_seeded_when_hash_provided() -> None:
    session = await _make_session()
    await seed_admin_api_keys(
        session,
        _make_settings(environment="production", admin_hash="deadbeef"),
    )

    calls = _execute_calls(session)
    assert len(calls) == 1
    _assert_on_conflict_do_nothing(calls[0])
    params = calls[0].compile(dialect=pg_dialect()).params
    assert params["key_hash"] == "deadbeef"
    assert params["name"] == PROD_KEY_NAME


@pytest.mark.asyncio
async def test_both_keys_seeded_in_development_when_hash_provided() -> None:
    session = await _make_session()
    await seed_admin_api_keys(
        session,
        _make_settings(environment="development", admin_hash="cafe"),
    )

    calls = _execute_calls(session)
    assert len(calls) == 2
    hashes = [c.compile(dialect=pg_dialect()).params["key_hash"] for c in calls]
    assert DEV_KEY_HASH in hashes
    assert "cafe" in hashes
    for stmt in calls:
        _assert_on_conflict_do_nothing(stmt)


@pytest.mark.asyncio
async def test_upsert_reports_created_when_rowcount_positive() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
    assert await _upsert_admin_key(session, key_hash="h", name="n") is True


@pytest.mark.asyncio
async def test_upsert_reports_not_created_when_rowcount_zero() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
    assert await _upsert_admin_key(session, key_hash="h", name="n") is False
