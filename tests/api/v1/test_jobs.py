"""
tests/api/v1/test_jobs.py — Tests for the GET /jobs/stats endpoint.

ai.jobs rows are seeded into a real in-memory SQLite session (the same
pattern as src/tests/test_suggestions_service.py) and the endpoint is
exercised over ASGI, so the assertions are about the response alone.

The app is driven through httpx.AsyncClient rather than TestClient so the
request runs on the test's event loop — the one the aiosqlite session is
bound to.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import JSON, MetaData, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import get_db, require_api_key
from app.main import app
from app.models.api_key import ApiKey
from app.models.job import Job

USER_ID = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
# Naive UTC, matching how ai.jobs stores timestamps.
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _api_key_record() -> ApiKey:
    record = ApiKey()
    record.id = USER_ID
    record.key_hash = "irrelevant"
    record.name = "test-key"
    record.permissions = []
    record.is_active = True
    record.owner_user_id = 42
    record.owner_org_id = None
    record.created_at = NOW
    record.expires_at = None
    return record


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine = engine.execution_options(schema_translate_map={"ai": None})

    # Clone Job into a fixture-local MetaData so the SQLite type patch never
    # leaks into the shared model metadata.
    scratch_metadata = MetaData()
    job_table = Job.__table__.to_metadata(scratch_metadata)  # type: ignore[attr-defined]
    for col in job_table.columns:
        if isinstance(col.type, JSONB):
            col.type = JSON()

    # Register PostgreSQL's now() function for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def register_now(dbapi_conn, connection_record) -> None:
        dbapi_conn.create_function(
            "now",
            0,
            lambda: datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )

    async with engine.begin() as conn:
        await conn.run_sync(scratch_metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def api(db_session) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Unauthenticated client whose get_db yields the seeded SQLite session."""

    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def authed_api(api) -> httpx.AsyncClient:
    app.dependency_overrides[require_api_key] = lambda: _api_key_record()
    return api


async def _seed(
    db: AsyncSession,
    status: str,
    *,
    age: timedelta = timedelta(minutes=5),
    error_message: str | None = None,
    task_type: str = "ai_suggestion",
) -> None:
    """Insert a job whose current status was entered `age` ago."""
    db.add(
        Job(
            task_type=task_type,
            payload={"projectUnitId": 1, "secretVerseText": "In the beginning"},
            dedup_key=f"test:{uuid.uuid4()}",
            status=status,
            retry_count=0,
            error_message=error_message,
            created_at=NOW - age,
            updated_at=NOW - age,
        )
    )
    await db.commit()


async def test_counts_jobs_by_status(authed_api, db_session):
    await _seed(db_session, "queued")
    await _seed(db_session, "processing")
    await _seed(db_session, "processing")
    await _seed(db_session, "completed")
    await _seed(db_session, "completed")
    await _seed(db_session, "completed")
    await _seed(db_session, "failed", error_message="boom")

    response = await authed_api.get("/jobs/stats")

    assert response.status_code == 200
    assert response.json()["lifetime"] == {
        "queued": 1,
        "processing": 2,
        "completed": 3,
        "failed": 1,
    }


async def test_recent_counts_only_jobs_that_changed_status_within_the_window(
    authed_api, db_session
):
    await _seed(db_session, "completed", age=timedelta(days=3))
    await _seed(db_session, "failed", age=timedelta(days=3), error_message="old")
    await _seed(db_session, "failed", age=timedelta(hours=1), error_message="new")
    await _seed(db_session, "queued", age=timedelta(minutes=1))

    response = await authed_api.get("/jobs/stats")

    body = response.json()
    assert body["window_hours"] == 24
    assert body["recent"] == {
        "queued": 1,
        "processing": 0,
        "completed": 0,
        "failed": 1,
    }
    assert body["lifetime"] == {
        "queued": 1,
        "processing": 0,
        "completed": 1,
        "failed": 2,
    }


async def test_window_is_adjustable(authed_api, db_session):
    await _seed(db_session, "failed", age=timedelta(hours=3), error_message="x")

    response = await authed_api.get("/jobs/stats", params={"window_hours": 2})

    body = response.json()
    assert body["window_hours"] == 2
    assert body["recent"]["failed"] == 0


def _parse(timestamp: str) -> datetime:
    return (
        datetime.fromisoformat(timestamp).astimezone(timezone.utc).replace(tzinfo=None)
    )


async def test_reports_oldest_backlog_and_newest_failure(authed_api, db_session):
    await _seed(db_session, "queued", age=timedelta(hours=2))
    await _seed(db_session, "queued", age=timedelta(minutes=10))
    await _seed(db_session, "processing", age=timedelta(minutes=30))
    await _seed(
        db_session,
        "failed",
        age=timedelta(days=2),
        error_message="Permanently failed after 3 retries: 401 Unauthorized",
    )
    await _seed(
        db_session,
        "failed",
        age=timedelta(minutes=5),
        error_message="Permanently failed after 3 retries: 402 RESOURCE_EXHAUSTED",
    )

    response = await authed_api.get("/jobs/stats")

    body = response.json()
    assert _parse(body["oldest_queued_at"]) == NOW - timedelta(hours=2)
    assert _parse(body["oldest_processing_at"]) == NOW - timedelta(minutes=30)
    assert _parse(body["oldest_failed_at"]) == NOW - timedelta(days=2)
    latest = body["latest_failure"]
    assert _parse(latest["failed_at"]) == NOW - timedelta(minutes=5)
    assert latest["task_type"] == "ai_suggestion"
    assert latest["error_message"] == (
        "Permanently failed after 3 retries: 402 RESOURCE_EXHAUSTED"
    )


async def test_no_failures_reports_null_failure_fields(authed_api, db_session):
    await _seed(db_session, "completed")

    response = await authed_api.get("/jobs/stats")

    body = response.json()
    assert body["lifetime"]["failed"] == 0
    assert body["recent"]["failed"] == 0
    assert body["oldest_failed_at"] is None
    assert body["latest_failure"] is None
    assert body["oldest_queued_at"] is None
    assert body["oldest_processing_at"] is None


async def test_empty_table_reports_zero_counts(authed_api):
    response = await authed_api.get("/jobs/stats")

    assert response.status_code == 200
    zero = {"queued": 0, "processing": 0, "completed": 0, "failed": 0}
    assert response.json()["lifetime"] == zero
    assert response.json()["recent"] == zero


async def test_latest_failure_redacts_credentials_in_error_message(
    authed_api, db_session
):
    await _seed(
        db_session,
        "failed",
        error_message=(
            "Permanently failed after 3 retries: Client error '403 Forbidden' for "
            "url 'https://generativelanguage.googleapis.com/v1beta/models?"
            "key=AIzaSyLEAKED123' (Authorization: Bearer eyJleaked.tok.en; "
            "api_key=fai_leaked_456)"
        ),
    )

    response = await authed_api.get("/jobs/stats")

    message = response.json()["latest_failure"]["error_message"]
    for secret in ("AIzaSyLEAKED123", "eyJleaked.tok.en", "fai_leaked_456"):
        assert secret not in message
    assert message.startswith(
        "Permanently failed after 3 retries: Client error '403 Forbidden'"
    )
    assert "[REDACTED]" in message


async def test_response_never_contains_job_payloads(authed_api, db_session):
    for status in ("queued", "processing", "completed", "failed"):
        await _seed(db_session, status, error_message="boom")

    response = await authed_api.get("/jobs/stats")

    assert response.status_code == 200
    assert "payload" not in response.text
    assert "secretVerseText" not in response.text
    assert "In the beginning" not in response.text


async def test_missing_api_key_is_rejected(api):
    response = await api.get("/jobs/stats")

    assert response.status_code == 401


async def test_unknown_api_key_is_rejected(api):
    with patch(
        "app.security.auth.get_api_key_by_hash",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await api.get("/jobs/stats", headers={"X-API-Key": "fai_unknown"})

    assert response.status_code == 401
