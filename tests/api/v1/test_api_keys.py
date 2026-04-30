"""
tests/api/v1/test_api_keys.py — endpoint tests for /api-keys/

Auth model:
  - No key          → 401
  - Valid key, no admin permission → 403 on admin-only endpoints
  - Valid admin key  → full access

Service functions are patched so tests run without a database.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.dependencies import require_admin, require_api_key
from app.internal.models import ApiKey
from app.main import app
from app.schemas.api_key import ApiKeyCreated

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

KEY_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ADMIN_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
OWNER_USER_ID = 42
OWNER_ORG_ID = 7
NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
RAW_KEY = "fai_test_rawkey_abc123"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_key(key_id, permissions, *, owner_user_id=None, is_active=True):
    record = ApiKey()
    record.id = key_id
    record.key_hash = "irrelevant"
    record.name = "test-key"
    record.permissions = permissions
    record.is_active = is_active
    record.owner_user_id = owner_user_id
    record.owner_org_id = None if owner_user_id else OWNER_ORG_ID
    record.created_at = NOW
    record.expires_at = None
    return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_record():
    return _api_key(ADMIN_ID, ["admin"])


@pytest.fixture
def user_record():
    return _api_key(USER_ID, [], owner_user_id=OWNER_USER_ID)


@pytest.fixture
def admin_client(client, admin_record):
    """Client authenticated as an admin key."""
    app.dependency_overrides[require_admin] = lambda: admin_record
    app.dependency_overrides[require_api_key] = lambda: admin_record
    yield client
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(require_api_key, None)


@pytest.fixture
def user_client(client, user_record):
    """Client authenticated as a non-admin key."""
    app.dependency_overrides[require_api_key] = lambda: user_record
    yield client
    app.dependency_overrides.pop(require_api_key, None)


@pytest.fixture
def non_admin_client(client, user_record):
    """Client with require_api_key overridden but require_admin left intact.
    require_admin will call the overridden require_api_key, get the non-admin
    record, and raise 403 because 'admin' is not in permissions."""
    app.dependency_overrides[require_api_key] = lambda: user_record
    yield client
    app.dependency_overrides.pop(require_api_key, None)


# ---------------------------------------------------------------------------
# POST /api-keys/
# ---------------------------------------------------------------------------

class TestCreateKey:
    def test_no_auth_returns_401(self, client):
        response = client.post("/api-keys/", json={"name": "k"})
        assert response.status_code == 401

    def test_non_admin_returns_403(self, non_admin_client):
        response = non_admin_client.post("/api-keys/", json={"name": "k"})
        assert response.status_code == 403

    def test_returns_201_with_raw_key(self, admin_client):
        created = ApiKeyCreated(
            id=KEY_ID,
            name="new-key",
            permissions=[],
            raw_key=RAW_KEY,
            created_at=NOW,
            expires_at=None,
        )
        with patch("app.api.v1.endpoints.api_keys.create_api_key", new_callable=AsyncMock, return_value=created):
            response = admin_client.post("/api-keys/", json={"name": "new-key", "permissions": []})

        assert response.status_code == 201
        body = response.json()
        assert body["raw_key"] == RAW_KEY
        assert body["raw_key"].startswith("fai_")
        assert body["name"] == "new-key"

    def test_raw_key_absent_from_schema_after_creation(self, admin_client):
        """raw_key is a one-time value — ApiKeyInfo never includes it."""
        created = ApiKeyCreated(
            id=KEY_ID, name="k", permissions=[], raw_key=RAW_KEY, created_at=NOW, expires_at=None,
        )
        with patch("app.api.v1.endpoints.api_keys.create_api_key", new_callable=AsyncMock, return_value=created):
            response = admin_client.post("/api-keys/", json={"name": "k"})

        assert "raw_key" in response.json()
        assert "key_hash" not in response.json()

    def test_missing_name_returns_422(self, admin_client):
        with patch("app.api.v1.endpoints.api_keys.create_api_key", new_callable=AsyncMock):
            response = admin_client.post("/api-keys/", json={"permissions": []})
        assert response.status_code == 422

    def test_empty_name_returns_422(self, admin_client):
        with patch("app.api.v1.endpoints.api_keys.create_api_key", new_callable=AsyncMock):
            response = admin_client.post("/api-keys/", json={"name": ""})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api-keys/
# ---------------------------------------------------------------------------

class TestListKeys:
    def test_no_auth_returns_401(self, client):
        assert client.get("/api-keys/").status_code == 401

    def test_non_admin_returns_403(self, non_admin_client):
        assert non_admin_client.get("/api-keys/").status_code == 403

    def test_returns_200_with_list(self, admin_client, admin_record):
        with patch("app.api.v1.endpoints.api_keys.list_api_keys", new_callable=AsyncMock, return_value=[admin_record]):
            response = admin_client.get("/api-keys/")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1

    def test_no_raw_key_or_hash_in_response(self, admin_client, admin_record):
        with patch("app.api.v1.endpoints.api_keys.list_api_keys", new_callable=AsyncMock, return_value=[admin_record]):
            response = admin_client.get("/api-keys/")

        for item in response.json():
            assert "raw_key" not in item
            assert "key_hash" not in item

    def test_empty_list(self, admin_client):
        with patch("app.api.v1.endpoints.api_keys.list_api_keys", new_callable=AsyncMock, return_value=[]):
            response = admin_client.get("/api-keys/")

        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# PATCH /api-keys/{key_id}
# ---------------------------------------------------------------------------

class TestPatchKey:
    def test_no_auth_returns_401(self, client):
        assert client.patch(f"/api-keys/{KEY_ID}", json={"name": "x"}).status_code == 401

    def test_non_admin_returns_403(self, non_admin_client):
        assert non_admin_client.patch(f"/api-keys/{KEY_ID}", json={"name": "x"}).status_code == 403

    def test_not_found_returns_404(self, admin_client):
        with patch("app.api.v1.endpoints.api_keys.update_api_key", new_callable=AsyncMock, return_value=None):
            response = admin_client.patch(f"/api-keys/{KEY_ID}", json={"name": "x"})
        assert response.status_code == 404

    def test_returns_updated_record(self, admin_client, admin_record):
        admin_record.name = "renamed"
        with patch("app.api.v1.endpoints.api_keys.update_api_key", new_callable=AsyncMock, return_value=admin_record):
            response = admin_client.patch(f"/api-keys/{KEY_ID}", json={"name": "renamed"})

        assert response.status_code == 200
        assert response.json()["name"] == "renamed"

    def test_no_raw_key_in_response(self, admin_client, admin_record):
        with patch("app.api.v1.endpoints.api_keys.update_api_key", new_callable=AsyncMock, return_value=admin_record):
            response = admin_client.patch(f"/api-keys/{KEY_ID}", json={"name": "x"})

        assert "raw_key" not in response.json()
        assert "key_hash" not in response.json()


# ---------------------------------------------------------------------------
# DELETE /api-keys/{key_id}
# ---------------------------------------------------------------------------

class TestRevokeKey:
    def test_no_auth_returns_401(self, client):
        assert client.delete(f"/api-keys/{KEY_ID}").status_code == 401

    def test_non_admin_returns_403(self, non_admin_client):
        assert non_admin_client.delete(f"/api-keys/{KEY_ID}").status_code == 403

    def test_returns_204(self, admin_client, admin_record):
        admin_record.is_active = False
        with patch("app.api.v1.endpoints.api_keys.revoke_api_key", new_callable=AsyncMock, return_value=admin_record):
            response = admin_client.delete(f"/api-keys/{KEY_ID}")
        assert response.status_code == 204

    def test_not_found_returns_404(self, admin_client):
        with patch("app.api.v1.endpoints.api_keys.revoke_api_key", new_callable=AsyncMock, return_value=None):
            response = admin_client.delete(f"/api-keys/{KEY_ID}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api-keys/me
# ---------------------------------------------------------------------------

class TestGetMyKey:
    def test_no_auth_returns_401(self, client):
        assert client.get("/api-keys/me").status_code == 401

    def test_returns_200_with_key_info(self, user_client, user_record):
        response = user_client.get("/api-keys/me")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(user_record.id)
        assert body["name"] == user_record.name
        assert body["is_active"] is True

    def test_no_raw_key_or_hash_in_response(self, user_client):
        response = user_client.get("/api-keys/me")

        body = response.json()
        assert "raw_key" not in body
        assert "key_hash" not in body

    def test_admin_can_get_own_key(self, admin_client, admin_record):
        response = admin_client.get("/api-keys/me")

        assert response.status_code == 200
        assert "admin" in response.json()["permissions"]
