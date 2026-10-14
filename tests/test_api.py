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
