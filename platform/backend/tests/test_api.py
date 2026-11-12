from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CALLS, make_settings


def test_health_and_config(client):
    assert client.get("/health").json() == {"status": "ok"}
    cfg = client.get("/api/config").json()
    assert cfg["jenkins"] and cfg["prometheus"] and cfg["release_state"]


def test_jenkins_event_ingest_and_listing(client):
    r = client.post("/api/events/jenkins", json={
        "event": "deploy", "status": "success", "build": "11", "image_tag": "11-def",
        "environment": "production", "build_url": "http://jenkins/job/demo-app/11/"})
    assert r.status_code == 201
    events = client.get("/api/events").json()
    assert events[0]["event"] == "deploy"
    assert events[0]["payload"]["build_url"].endswith("/11/")
    assert client.post("/api/events/jenkins", json={"status": "x"}).status_code == 422


def test_ingest_token_enforced(tmp_path):
    app = create_app(make_settings(tmp_path, ingest_token="s3cret"))
    with TestClient(app) as c:
        body = {"event": "pipeline", "status": "started"}
        assert c.post("/api/events/jenkins", json=body).status_code == 401
        assert c.post("/api/events/jenkins", json=body,
                      headers={"X-Platform-Token": "wrong"}).status_code == 401
        assert c.post("/api/events/jenkins", json=body,
                      headers={"X-Platform-Token": "s3cret"}).status_code == 201
        assert c.post("/api/alerts/alertmanager", json={"alerts": []}).status_code == 401


def test_dashboard_aggregates_everything(client):
    client.post("/api/events/jenkins", json={"event": "pipeline", "status": "success",
                                             "build": "11"})
    d = client.get("/api/dashboard").json()
    assert d["service"]["info"]["data"]["version"] == "11-def"
    assert d["service"]["info"]["data"]["ready"] is True
    assert d["service"]["error_ratio"]["data"] == 0.25
    assert d["pipeline"]["builds"]["data"][0]["result"] == "RUNNING"
    assert d["pipeline"]["last_event"]["status"] == "success"
    assert d["release"]["last_good_image"] == "repo/demo-app:10-aaa"
    assert d["alerts"]["data"][0]["alertname"] == "HighErrorRate"
    assert d["incidents"]["open_count"] == 0


def test_dashboard_degrades_without_upstreams(bare_client):
    d = bare_client.get("/api/dashboard").json()
    assert d["service"]["info"]["ok"] is False
    assert "not configured" in d["pipeline"]["builds"]["error"]
    assert d["release"]["available"] is False


def test_pipeline_builds_and_detail(client):
    builds = client.get("/api/pipeline/builds").json()
    assert builds["ok"]
    assert builds["data"][0]["parameters"] == {"DEPLOY_ENV": "production"}
    assert builds["data"][1]["result"] == "FAILURE"

    detail = client.get("/api/pipeline/builds/11").json()
    assert detail["stages"]["data"][1] == {"name": "Post-deploy smoke test", "status": "FAILED",
                                           "duration_ms": 4000, "started_at_ms": None}
    assert detail["tests"]["data"]["failed"] == 1
    assert detail["tests"]["data"]["failures"][0]["test"] == "t.test_x"

    log = client.get("/api/pipeline/builds/11/log?lines=20").json()
    assert log["data"].splitlines() == [f"line {i}" for i in range(480, 500)]


def test_deployments(client):
    d = client.get("/api/deployments").json()
    assert d["release"]["current_image"] == "repo/demo-app:11-def"
    assert d["history"][0]["image"] == "repo/demo-app:11-def"  # newest first
    assert d["running"]["data"]["version"] == "11-def"


def test_monitoring_series_and_targets(client):
    m = client.get("/api/monitoring?minutes=30").json()
    assert m["series"]["error_ratio"]["points"][-1][1] == 0.6
    assert m["targets"]["data"][0]["health"] == "up"
    assert m["step"] == 15


def test_logs_query_building_and_validation(client):
    r = client.get("/api/logs", params={"level": "error,warning", "search": 'say "hi"',
                                        "event": "http_request"}).json()
    assert r["query"] == ('{service="demo-app", level=~"ERROR|WARNING", event="http_request"}'
                          ' |= "say \\"hi\\""')
    assert r["data"][0]["json"]["level"] == "ERROR"
    sent = [c for c in CALLS if c.url.host == "loki"][-1]
    assert sent.url.params["query"] == r["query"]

    assert client.get("/api/logs", params={"level": "LOUD"}).status_code == 422
    assert client.get("/api/logs", params={"event": 'x"}'}).status_code == 422
