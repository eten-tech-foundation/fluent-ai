# tests/api/v1/test_api_keys.py — tests for the API key management endpoints.
#
# Endpoints under test:
#   POST   /admin/api-keys         create_key  — admin only
#   GET    /admin/api-keys         list_keys   — admin only
#   PATCH  /admin/api-keys/{id}    patch_key   — admin only
#   DELETE /admin/api-keys/{id}    revoke_key  — admin only
#   GET    /api-keys/me            get_my_key  — any valid key
#
# Test cases to implement:
#
#   def test_create_key_requires_admin(client, non_admin_api_key):
#       response = client.post("/admin/api-keys", headers={"X-API-Key": non_admin_api_key}, json={...})
#       assert response.status_code == 403
#
#   def test_create_key_returns_raw_key_once(client, admin_api_key):
#       response = client.post("/admin/api-keys", headers={"X-API-Key": admin_api_key},
#           json={"name": "test-key", "permissions": []})
#       assert response.status_code == 201
#       body = response.json()
#       assert "raw_key" in body
#       assert body["raw_key"].startswith("fai_")
#
#   def test_revoke_key_makes_key_unusable(client, admin_api_key, db_session):
#       # Create a key, revoke it, then try to use it — expect 403.
#       ...
#
#   def test_get_my_key_returns_current_key_info(client, valid_api_key):
#       response = client.get("/api-keys/me", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 200
#       assert "raw_key" not in response.json()  # never exposed after creation
