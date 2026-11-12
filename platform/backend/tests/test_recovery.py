import httpx
import pytest
from fastapi.testclient import TestClient

import tests.conftest as fakes
from app.main import create_app
from tests.conftest import CALLS, alert, handler, make_settings, write_state

TARGET = "repo/demo-app:10-aaa"


def make_client(tmp_path, **overrides):
    write_state(tmp_path)
    settings = make_settings(tmp_path, jenkins_user="platform", jenkins_token="tok", **overrides)
    return TestClient(create_app(settings, transport=httpx.MockTransport(handler)))


@pytest.fixture
def rc(tmp_path):
    CALLS.clear()
    fakes.JENKINS_TRIGGER_FAILS = False
    with make_client(tmp_path) as c:
        yield c


def request(c, action="rollback", **kw):
    body = {"action": action, "reason": "error rate after release 11", "requested_by": "asha",
            **kw}
    return c.post("/api/recovery/actions", json=body)


def test_options(rc):
    o = rc.get("/api/recovery/options").json()
    assert o["blockers"] == []
    assert o["rollback"] == {"available": True, "default_target": TARGET, "reason": None,
                             "targets": [TARGET]}
    assert o["restart"]["available"] is True
    assert o["active"] is None
    assert o["approval_token_required"] is False


def test_full_rollback_flow_linked_to_incident(rc):
    inc_id = rc.post("/api/alerts/alertmanager",
                     json={"alerts": [alert("HighErrorRate")]}).json()["opened_incidents"][0]

    r = request(rc, incident_id=inc_id)
    assert r.status_code == 201
    a = r.json()
    assert a["status"] == "pending_approval"
    assert a["target_image"] == TARGET and a["from_image"] == "repo/demo-app:11-def"
    assert rc.get("/api/recovery/options").json()["active"]["id"] == a["id"]

    r = rc.post(f"/api/recovery/actions/{a['id']}/approve", json={"by": "ravi", "note": "go"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"
    assert r.json()["jenkins_queue"] == "http://jenkins/queue/item/77/"
    trigger = [c for c in CALLS if c.method == "POST" and c.url.host == "jenkins"][-1]
    body = trigger.content.decode()
    assert "ACTION=rollback" in body and "REQUEST_ID=" in body and "APPROVED_BY=ravi" in body
    assert trigger.headers["authorization"].startswith("Basic ")

    smoke = {"smoke_test": "passed", "checks": []}
    r = rc.post(f"/api/recovery/actions/{a['id']}/result",
                json={"status": "succeeded", "detail": "ok", "build": "3", "smoke_test": smoke})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "succeeded" and done["jenkins_build"] == "3"
    assert done["health"]["smoke_test"] == smoke
    check = done["health"]["platform_check"]
    assert check["reachable"] and check["ready"] and check["version"] == "11-def"
    assert check["version_matches_target"] is False  # fake app still reports the old version

    notes = [n["note"] for n in rc.get(f"/api/incidents/{inc_id}").json()["notes"]]
    assert notes[0].startswith("asha requested rollback")
    assert notes[1].startswith("ravi approved")
    assert "succeeded" in notes[2]
    assert rc.get("/api/recovery/options").json()["active"] is None


def test_reject(rc):
    a = request(rc).json()
    r = rc.post(f"/api/recovery/actions/{a['id']}/reject", json={"by": "ravi", "note": "no"})
    assert r.json()["status"] == "rejected" and r.json()["decision_note"] == "no"
    again = rc.post(f"/api/recovery/actions/{a['id']}/approve", json={"by": "ravi"})
    assert again.status_code == 409
    assert not [c for c in CALLS if c.method == "POST" and c.url.host == "jenkins"]


def test_only_one_active_action(rc):
    assert request(rc).status_code == 201
    r = request(rc, action="restart")
    assert r.status_code == 409 and "already pending" in r.json()["detail"]


def test_restart_targets_current_image(rc):
    a = request(rc, action="restart").json()
    assert a["target_image"] == "repo/demo-app:11-def"


@pytest.mark.parametrize("target,code", [
    ("evil/image:latest; rm -rf /", 422),     # not in release history
    ("repo/demo-app:11-def", 409),            # already running
])
def test_rollback_target_validation(rc, target, code):
    assert request(rc, target_image=target).status_code == code


def test_input_validation(rc):
    assert request(rc, action="delete").status_code == 422
    assert request(rc, requested_by="x").status_code == 422           # too short
    assert request(rc, requested_by="a<script>").status_code == 422   # bad chars
    assert request(rc, incident_id=999).status_code == 404


def test_approval_token_and_four_eyes(tmp_path):
    with make_client(tmp_path, recovery_approval_token="sesame",
                     require_distinct_approver=True) as c:
        a = request(c).json()
        url = f"/api/recovery/actions/{a['id']}/approve"
        assert c.post(url, json={"by": "ravi"}).status_code == 403
        assert c.post(url, json={"by": "ravi", "approval_token": "nope"}).status_code == 403
        r = c.post(url, json={"by": "Asha", "approval_token": "sesame"})
        assert r.status_code == 403 and "different person" in r.json()["detail"]
        ok = c.post(url, json={"by": "ravi", "approval_token": "sesame"})
        assert ok.json()["status"] == "running"


def test_approve_without_jenkins_keeps_request_pending(tmp_path):
    write_state(tmp_path)
    app = create_app(make_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        assert c.get("/api/recovery/options").json()["blockers"]
        a = request(c).json()
        assert c.post(f"/api/recovery/actions/{a['id']}/approve",
                      json={"by": "ravi"}).status_code == 503
        assert c.get(f"/api/recovery/actions/{a['id']}").json()["status"] == "pending_approval"


def test_jenkins_trigger_failure_marks_failed(rc):
    fakes.JENKINS_TRIGGER_FAILS = True
    a = request(rc).json()
    r = rc.post(f"/api/recovery/actions/{a['id']}/approve", json={"by": "ravi"})
    assert r.json()["status"] == "failed"
    assert "could not start Jenkins job" in r.json()["detail"]
    assert rc.get("/api/recovery/options").json()["active"] is None


def test_result_rules(rc):
    a = request(rc).json()
    url = f"/api/recovery/actions/{a['id']}/result"
    assert rc.post(url, json={"status": "succeeded"}).status_code == 409   # not approved yet
    rc.post(f"/api/recovery/actions/{a['id']}/approve", json={"by": "ravi"})
    assert rc.post(url, json={"status": "maybe"}).status_code == 422
    assert rc.post(url, json={"status": "failed", "detail": "health check"}).json()[
        "status"] == "failed"
    assert rc.post(url, json={"status": "succeeded"}).status_code == 409   # already finished


def test_result_requires_ingest_token_when_configured(tmp_path):
    with make_client(tmp_path, ingest_token="s3") as c:
        a = request(c).json()
        c.post(f"/api/recovery/actions/{a['id']}/approve", json={"by": "ravi"})
        url = f"/api/recovery/actions/{a['id']}/result"
        assert c.post(url, json={"status": "succeeded"}).status_code == 401
        assert c.post(url, json={"status": "succeeded"},
                      headers={"X-Platform-Token": "s3"}).status_code == 200


def test_stale_requests_expire_and_runs_time_out(rc):
    a = request(rc).json()
    db = rc.app.state.ctx.db
    with db.tx() as conn:
        conn.execute("UPDATE recovery_actions SET requested_at = '2020-01-01T00:00:00+00:00'")
    assert rc.get(f"/api/recovery/actions/{a['id']}").json()["status"] == "expired"

    b = request(rc).json()
    rc.post(f"/api/recovery/actions/{b['id']}/approve", json={"by": "ravi"})
    with db.tx() as conn:
        conn.execute("UPDATE recovery_actions SET started_at = '2020-01-01T00:00:00+00:00' "
                     "WHERE id = ?", (b["id"],))
    assert rc.get("/api/recovery/actions").json()[0]["status"] == "timed_out"


def test_no_release_state(bare_client):
    r = bare_client.post("/api/recovery/actions", json={
        "action": "restart", "reason": "stuck", "requested_by": "asha"})
    assert r.status_code == 409
