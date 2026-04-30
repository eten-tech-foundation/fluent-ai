# tests/api/v1/test_projects.py — tests for the projects endpoints.
#
# Endpoints under test:
#   GET /projects/          list_projects — requires valid API key
#   GET /projects/{id}      get_project   — requires valid API key
#   GET /projects/_verify-permissions     — requires admin key
#
# Test cases to implement:
#
#   def test_list_projects_requires_auth(client):
#       response = client.get("/projects/")
#       assert response.status_code == 401
#
#   def test_list_projects_returns_paginated_list(client, valid_api_key, seeded_projects):
#       response = client.get("/projects/", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 200
#       body = response.json()
#       assert "items" in body
#       assert "total" in body
#
#   def test_get_project_not_found(client, valid_api_key):
#       response = client.get("/projects/999999", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 404
#
#   def test_get_project_returns_project(client, valid_api_key, seeded_project):
#       response = client.get(f"/projects/{seeded_project.id}", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 200
#       assert response.json()["id"] == seeded_project.id
