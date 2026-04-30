import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.main import app


async def _mock_get_db():
    yield AsyncMock(spec=AsyncSession)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = _mock_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
