"""
tests/test_health.py — Tests for the /health endpoint the deploy pipeline polls.
"""

from fastapi.testclient import TestClient


def test_health_reports_healthy(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_identifies_the_running_build(client: TestClient):
    """The deployment runbooks read `commit` off /health to confirm which
    build is live, and promotion is by commit SHA rather than by tag — so
    losing these keys would leave no way to tell QA and prod apart."""
    body = client.get("/health").json()

    assert set(body) == {"status", "version", "environment", "commit"}
    assert body["environment"]
    assert body["commit"]
