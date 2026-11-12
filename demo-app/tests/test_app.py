import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TOKEN = "test-token"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(version="9.9.9", environment="test")))


@pytest.fixture
def chaos_client() -> TestClient:
    app = create_app(Settings(environment="test", chaos_enabled=True, chaos_token=TOKEN))
    c = TestClient(app)
    c.headers["x-chaos-token"] = TOKEN
    return c


# ---------------------------------------------------------------- ops endpoints
def test_info_reports_version(client):
    body = client.get("/").json()
    assert body["version"] == "9.9.9"
    assert body["env"] == "test"


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"]["inventory-db"] == "up"


def test_request_id_is_echoed_or_generated(client):
    assert client.get("/health", headers={"x-request-id": "abc"}).headers["x-request-id"] == "abc"
    assert len(client.get("/health").headers["x-request-id"]) == 32


def test_metrics_exposes_request_counters(client):
    client.get("/api/items")
    text = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/api/items",status="200"}' in text
    assert "http_request_duration_seconds_bucket" in text
    assert 'app_info{env="test",service="demo-app",version="9.9.9"}' in text


def test_metrics_use_route_template_not_raw_path(client):
    client.get("/api/items/1")
    client.get("/does-not-exist")
    text = client.get("/metrics").text
    assert 'route="/api/items/{item_id}"' in text
    assert 'route="unmatched"' in text
    assert 'route="/does-not-exist"' not in text


# ------------------------------------------------------------------ inventory
def test_item_crud(client):
    assert len(client.get("/api/items").json()) == 3

    created = client.post("/api/items", json={"name": "bolt", "quantity": 5, "price": 0.1})
    assert created.status_code == 201
    item_id = created.json()["id"]

    assert client.get(f"/api/items/{item_id}").json()["name"] == "bolt"
    assert client.delete(f"/api/items/{item_id}").status_code == 204
    assert client.get(f"/api/items/{item_id}").status_code == 404
    assert client.delete(f"/api/items/{item_id}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "quantity": 1, "price": 1},
        {"name": "x", "quantity": -1, "price": 1},
        {"name": "x", "quantity": 1, "price": -5},
        {"name": "x"},
    ],
)
def test_item_validation(client, payload):
    assert client.post("/api/items", json=payload).status_code == 422


# ---------------------------------------------------------- failure injection
def test_chaos_hidden_when_disabled(client):
    assert client.get("/chaos").status_code == 404
    assert client.post("/chaos", json={"error_rate": 1}).status_code == 404


def test_chaos_requires_token(chaos_client):
    assert chaos_client.get("/chaos", headers={"x-chaos-token": "wrong"}).status_code == 403
    assert chaos_client.get("/chaos").status_code == 200


def test_chaos_rejects_out_of_range_values(chaos_client):
    assert chaos_client.post("/chaos", json={"error_rate": 2}).status_code == 422
    assert chaos_client.post("/chaos", json={"memory_leak_mb": 1000}).status_code == 422


def test_error_injection_breaks_api_but_not_health(chaos_client):
    chaos_client.post("/chaos", json={"error_rate": 1.0})
    assert chaos_client.get("/api/items").status_code == 500
    assert chaos_client.get("/health").status_code == 200

    chaos_client.delete("/chaos")
    assert chaos_client.get("/api/items").status_code == 200


def test_dependency_failure_returns_503_and_fails_readiness(chaos_client):
    chaos_client.post("/chaos", json={"dependency_failure": True})
    resp = chaos_client.get("/api/items")
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"]
    assert chaos_client.get("/ready").status_code == 503
    assert "dependency_up{dependency=\"inventory-db\"} 0.0" in chaos_client.get("/metrics").text

    chaos_client.delete("/chaos")
    assert chaos_client.get("/ready").status_code == 200


def test_latency_injection(chaos_client):
    chaos_client.post("/chaos", json={"latency_ms": 200})
    start = time.perf_counter()
    chaos_client.get("/api/items")
    assert time.perf_counter() - start >= 0.2


def test_memory_leak_accumulates_and_resets(chaos_client):
    chaos_client.post("/chaos", json={"memory_leak_mb": 1})
    chaos_client.get("/api/items")
    chaos_client.get("/api/items")
    assert chaos_client.get("/chaos").json()["leaked_bytes"] == 2 * 1024 * 1024

    chaos_client.delete("/chaos")
    assert chaos_client.get("/chaos").json()["leaked_bytes"] == 0


def test_chaos_settings_merge(chaos_client):
    chaos_client.post("/chaos", json={"latency_ms": 10})
    state = chaos_client.post("/chaos", json={"error_rate": 0.5}).json()
    assert state["latency_ms"] == 10
    assert state["error_rate"] == 0.5
