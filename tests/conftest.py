# conftest.py — shared pytest fixtures.
#
# This file is auto-loaded by pytest before any test module.
# Define fixtures here that are needed across multiple test files.
#
# Key fixtures to implement:
#
#   @pytest.fixture
#   def client() -> TestClient:
#       # Synchronous test client for route-level tests.
#       from fastapi.testclient import TestClient
#       from app.main import app
#       return TestClient(app)
#
#   @pytest.fixture
#   async def db_session() -> AsyncGenerator[AsyncSession, None]:
#       # Override the get_db dependency with a test session that rolls back
#       # after each test so tests are isolated and don't pollute each other.
#       # Wire up with:
#       #   from app.dependencies import get_db
#       #   app.dependency_overrides[get_db] = lambda: db_session
#       ...
#
#   @pytest.fixture
#   def admin_api_key(db_session) -> str:
#       # Create a seeded admin API key for tests that need auth.
#       # Return the raw key string (not the hash).
#       ...
#
# Required packages (already in pyproject.toml dev dependencies):
#   pytest, pytest-asyncio, httpx
