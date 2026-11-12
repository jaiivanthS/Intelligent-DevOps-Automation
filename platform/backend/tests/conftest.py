"""Fake upstreams (Jenkins, Prometheus, Loki, Alertmanager, demo-app) via httpx.MockTransport."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

CALLS: list[httpx.Request] = []
JENKINS_TRIGGER_FAILS = False


def _vector(value):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {}, "value": [time.time(), str(value)]}]}}


def _matrix(values):
    now = int(time.time())
    return {"status": "success", "data": {"resultType": "matrix", "result": [
        {"metric": {}, "values": [[now - 30 * (len(values) - i), str(v)]
                                  for i, v in enumerate(values)]}]}}


def handler(request: httpx.Request) -> httpx.Response:
    CALLS.append(request)
    host, path = request.url.host, request.url.path
    q = request.url.params.get("query", "")

    if host == "prom":
        if path == "/api/v1/query":
            return httpx.Response(200, json=_vector(0.25 if "status=~" in q else 4.0))
        if path == "/api/v1/query_range":
            if "status=~" in q:  # error ratio climbs during the incident
                return httpx.Response(200, json=_matrix([0, 0, 0, 0.3, 0.5, 0.6]))
            # everything else stays at a plausible, flat level
            flat = (0.1 if "cpu_seconds" in q else 9e7 if "resident_memory" in q
                    else 0.05 if "histogram_quantile" in q else 2 if "in_progress" in q else 1)
            return httpx.Response(200, json=_matrix([flat] * 6))
        if path == "/api/v1/targets":
            return httpx.Response(200, json={"status": "success", "data": {"activeTargets": [
                {"labels": {"job": "demo-app", "instance": "demo-app:8000"}, "health": "up",
                 "lastError": ""}]}})
    if host == "loki" and path == "/loki/api/v1/query_range":
        lines = [json.dumps({"level": "ERROR", "msg": "Injected failure", "event": "chaos_error"}),
                 json.dumps({"level": "ERROR", "msg": "Injected failure", "event": "chaos_error"}),
                 json.dumps({"level": "ERROR", "msg": "request", "event": "http_request",
                             "status": 500})]
        now = time.time_ns()
        return httpx.Response(200, json={"status": "success", "data": {"result": [
            {"stream": {"service": "demo-app", "level": "ERROR"},
             "values": [[str(now - i), line] for i, line in enumerate(lines)]}]}})
    if host == "am" and path == "/api/v2/alerts":
        return httpx.Response(200, json=[{"labels": {"alertname": "HighErrorRate"},
                                          "annotations": {"summary": "5xx"},
                                          "startsAt": "2026-01-01T00:00:00Z",
                                          "status": {"state": "active"}}])
    if host == "jenkins":
        if request.method == "POST" and path == "/job/recovery/buildWithParameters":
            if JENKINS_TRIGGER_FAILS:
                return httpx.Response(500, text="boom")
            return httpx.Response(201, headers={"Location": "http://jenkins/queue/item/77/"})
        if path == "/job/demo-app/api/json":
            return httpx.Response(200, json={"builds": [
                {"number": 12, "building": True, "result": None, "timestamp": 1, "duration": 0,
                 "displayName": "#12 abc", "actions": [{}, {"parameters": [
                     {"name": "DEPLOY_ENV", "value": "production"}]}]},
                {"number": 11, "building": False, "result": "FAILURE", "timestamp": 1,
                 "duration": 5000, "displayName": "#11 def", "actions": []}]})
        if path == "/job/demo-app/11/wfapi/describe":
            return httpx.Response(200, json={"stages": [
                {"name": "Unit tests", "status": "SUCCESS", "durationMillis": 900},
                {"name": "Post-deploy smoke test", "status": "FAILED", "durationMillis": 4000}]})
        if path == "/job/demo-app/11/testReport/api/json":
            return httpx.Response(200, json={"passCount": 17, "failCount": 1, "skipCount": 0,
                                             "suites": [{"name": "s", "cases": [
                                                 {"className": "t", "name": "test_x",
                                                  "status": "FAILED", "errorDetails": "boom"}]}]})
        if path == "/job/demo-app/11/consoleText":
            return httpx.Response(200, text="\n".join(f"line {i}" for i in range(500)))
    if host == "app":
        if path == "/":
            return httpx.Response(200, json={"service": "demo-app", "version": "11-def",
                                             "env": "production"})
        if path == "/ready":
            return httpx.Response(200, json={"status": "ready"})
    return httpx.Response(404, json={"detail": f"unmocked {host}{path}"})


def make_settings(tmp_path, **overrides) -> Settings:
    base = dict(db_path=str(tmp_path / "test.db"), jenkins_url="http://jenkins",
                prometheus_url="http://prom", loki_url="http://loki",
                alertmanager_url="http://am", app_url="http://app",
                app_state_dir=str(tmp_path / "state"))
    base.update(overrides)
    return Settings(**base)


def write_state(tmp_path):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "current_image").write_text("repo/demo-app:11-def\n")
    (state / "last_good_image").write_text("repo/demo-app:10-aaa\n")
    (state / "app_env").write_text("production\n")
    (state / "releases.jsonl").write_text(
        '{"action":"deploy","result":"success","image":"repo/demo-app:10-aaa"}\n'
        '{"action":"promote","result":"success","image":"repo/demo-app:10-aaa"}\n'
        '{"action":"deploy","result":"success","image":"repo/demo-app:11-def"}\n')


@pytest.fixture
def client(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_image").write_text("repo/demo-app:11-def\n")
    (state / "last_good_image").write_text("repo/demo-app:10-aaa\n")
    (state / "app_env").write_text("production\n")
    (state / "releases.jsonl").write_text(
        '{"action":"deploy","result":"success","image":"repo/demo-app:10-aaa"}\n'
        '{"action":"promote","result":"success","image":"repo/demo-app:10-aaa"}\n'
        '{"action":"deploy","result":"success","image":"repo/demo-app:11-def"}\n')
    CALLS.clear()
    app = create_app(make_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def bare_client(tmp_path):
    """No upstreams configured at all."""
    app = create_app(Settings(db_path=str(tmp_path / "bare.db")))
    with TestClient(app) as c:
        yield c


def alert(name, status="firing", service="demo-app", severity="critical", category="errors",
          fp=None, **extra_labels):
    labels = {"alertname": name, "service": service, "severity": severity,
              "category": category, **extra_labels}
    return {"status": status, "labels": labels, "fingerprint": fp or f"fp-{name}",
            "annotations": {"summary": f"{name} summary"},
            "startsAt": "2026-01-01T00:00:00Z", "endsAt": "2026-01-01T00:10:00Z"}
