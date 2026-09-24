import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.main import app, settings as app_settings


async def _mock_get_db():
    yield AsyncMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def disable_suggestion_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """API and lifespan tests do not need the live Gemini/DB polling loop."""
    monkeypatch.setattr(app_settings, "enable_suggestion_worker", False)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = _mock_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
