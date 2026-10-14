from fastapi.testclient import TestClient

from maintainer_copilot.api import app

client = TestClient(app)


def test_generates_request_id_when_missing():
    response = client.get("/health")
    assert len(response.headers["x-request-id"]) == 32


def test_echoes_a_safe_incoming_request_id():
    response = client.get("/health", headers={"x-request-id": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"


def test_replaces_an_unsafe_incoming_request_id():
    response = client.get("/health", headers={"x-request-id": 'x", "level": "critical'})
    assert response.headers["x-request-id"] != 'x", "level": "critical'
    assert len(response.headers["x-request-id"]) == 32


def test_dry_run_rejects_a_non_issue_url():
    response = client.post("/triage/dry-run", json={"issue_url": "http://localhost:5432/secret"})
    assert response.status_code == 400


def test_dry_run_rejects_other_repositories():
    response = client.post("/triage/dry-run", json={"issue_url": "https://github.com/someone/else/issues/1"})
    assert response.status_code == 400
    assert "pydantic/pydantic" in response.json()["detail"]
