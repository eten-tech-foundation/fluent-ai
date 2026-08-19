"""Database integration tests for get_api_key_by_hash.

Exercises the actual SQLAlchemy query (not mocked) against an in-memory
SQLite database, confirming the lookup contract:
  * Returns a row matching key_hash regardless of is_active status.
  * Returns None for an unknown hash.

PostgreSQL-specific types (UUID, ARRAY) and constraints (num_nonnulls,
partial index) are patched/stripped for SQLite compatibility, following
the same pattern as src/tests/worker/conftest.py.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import JSON, CheckConstraint, MetaData, VARCHAR, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.api_key import ApiKey
from app.services.api_key import get_api_key_by_hash, hash_key


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A real AsyncSession backed by in-memory SQLite.

    Clones the api_keys table into a fixture-local MetaData, patches
    PostgreSQL-specific column types to SQLite-compatible equivalents,
    and strips PG-specific constraints (num_nonnulls check, partial index)
    that SQLite cannot evaluate. See src/tests/worker/conftest.py for
    the established pattern.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})

    scratch_metadata = MetaData()
    table = ApiKey.__table__.to_metadata(scratch_metadata)

    # Patch PG-specific column types to SQLite-compatible equivalents.
    for col in table.columns:
        if isinstance(col.type, UUID):
            col.type = VARCHAR(36)
        elif col.type.__class__.__name__ == "ARRAY":
            # sqlalchemy.ARRAY (generic) — not supported by SQLite.
            # Use JSON so list values can be bound directly.
            col.type = JSON()
            # Clear PG-specific server_default ('{}' array literal).
            col.server_default = None

    # Strip PG-specific constraints that SQLite cannot handle:
    #   - num_nonnulls check constraint (PG-only function)
    #   - partial index with postgresql_where (PG-only feature)
    table.constraints = {
        c for c in table.constraints if not _is_num_nonnulls_check(c)
    }
    table.indexes = set()  # drop all indexes (the only one is the partial index)

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: table.create(c, checkfirst=True))

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _is_num_nonnulls_check(constraint) -> bool:
    """Return True if a CheckConstraint uses the PG-only num_nonnulls function."""
    if not isinstance(constraint, CheckConstraint):
        return False
    return "num_nonnulls" in str(constraint.sqltext)


async def _insert_key(
    session: AsyncSession,
    *,
    raw_key: str,
    name: str,
    is_active: bool = True,
    owner_user_id: int = 1,
) -> None:
    """Insert an ApiKey row using raw SQL.

    The ORM's ARRAY type processor cannot bind Python lists to SQLite,
    so we bypass the ORM and insert via text() with a JSON string for
    the permissions column.
    """
    import json
    import uuid
    from datetime import datetime, timezone

    await session.execute(
        text(
            "INSERT INTO api_keys "
            "(id, key_hash, name, permissions, is_active, "
            "owner_user_id, owner_org_id, created_at, expires_at) "
            "VALUES (:id, :key_hash, :name, :permissions, :is_active, "
            ":owner_user_id, :owner_org_id, :created_at, :expires_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "key_hash": hash_key(raw_key),
            "name": name,
            "permissions": json.dumps([]),
            "is_active": is_active,
            "owner_user_id": owner_user_id,
            "owner_org_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": None,
        },
    )
    await session.commit()


@pytest.mark.asyncio
async def test_get_api_key_by_hash_returns_active_key(db_session: AsyncSession) -> None:
    """Active key is found by hash."""
    raw = "fai_active_test_key"
    await _insert_key(db_session, raw_key=raw, name="active-key")
    result = await get_api_key_by_hash(db_session, raw)
    assert result is not None
    assert result.name == "active-key"
    assert result.is_active is True


@pytest.mark.asyncio
async def test_get_api_key_by_hash_returns_inactive_key(db_session: AsyncSession) -> None:
    """Inactive (revoked) key is still returned — is_active filtering is
    require_api_key's responsibility, not the lookup's."""
    raw = "fai_inactive_test_key"
    await _insert_key(
        db_session, raw_key=raw, name="revoked-key", is_active=False
    )
    result = await get_api_key_by_hash(db_session, raw)
    assert result is not None
    assert result.name == "revoked-key"
    assert result.is_active is False


@pytest.mark.asyncio
async def test_get_api_key_by_hash_returns_none_for_unknown_hash(
    db_session: AsyncSession,
) -> None:
    """Unknown hash returns None."""
    result = await get_api_key_by_hash(db_session, "fai_nonexistent_key")
    assert result is None
