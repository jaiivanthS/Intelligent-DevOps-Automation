from tests.conftest import alert


def post_alerts(client, *alerts):
    resp = client.post("/api/alerts/alertmanager", json={"alerts": list(alerts)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_firing_alert_opens_incident_with_evidence(client):
    result = post_alerts(client, alert("HighErrorRate"))
    assert len(result["opened_incidents"]) == 1
    inc_id = result["opened_incidents"][0]

    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "open"
    assert inc["severity"] == "critical"
    assert inc["category"] == "errors"
    assert inc["title"] == "HighErrorRate summary"
    assert [a["alertname"] for a in inc["alerts"]] == ["HighErrorRate"]

    ev = inc["evidence"]  # collected by the background task
    assert ev["metrics"]["error_ratio"]["now"] == 0.6
    assert ev["metrics"]["error_ratio"]["baseline"] == 0
    assert ev["metrics"]["request_rate"]["now"] == 1
    assert ev["logs"]["error_lines"] == 3
    assert ev["logs"]["top_messages"][0] == {"msg": "Injected failure", "level": "ERROR",
                                             "count": 2}
    assert ev["release"]["current_image"] == "repo/demo-app:11-def"
    assert ev["release_history"][0]["image"] == "repo/demo-app:11-def"


def test_alerts_for_same_service_correlate_into_one_incident(client):
    first = post_alerts(client, alert("HighLatencyP95", severity="warning", category="latency"))
    second = post_alerts(client, alert("HighErrorRate"))
    assert second["opened_incidents"] == []
    inc = client.get(f"/api/incidents/{first['opened_incidents'][0]}").json()
    assert {a["alertname"] for a in inc["alerts"]} == {"HighLatencyP95", "HighErrorRate"}
    assert inc["severity"] == "critical"  # escalated to the worst alert
    assert inc["category"] == "latency"   # category of the first symptom is kept


def test_other_service_opens_separate_incident(client):
    a = post_alerts(client, alert("HighErrorRate"))
    b = post_alerts(client, alert("HostHighCpu", service="host", category="saturation"))
    assert a["opened_incidents"] != b["opened_incidents"]
    assert len(client.get("/api/incidents?status=active").json()) == 2


def test_incident_resolves_when_all_alerts_resolve_then_new_incident(client):
    inc_id = post_alerts(client, alert("HighErrorRate"), alert("DependencyDown",
                                                               category="dependency"))[
        "opened_incidents"][0]
    post_alerts(client, alert("HighErrorRate", status="resolved"))
    assert client.get(f"/api/incidents/{inc_id}").json()["status"] == "open"

    post_alerts(client, alert("DependencyDown", status="resolved", category="dependency"))
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "resolved"
    assert inc["resolved_at"]


def test_alert_soon_after_resolution_reopens_incident(client):
    # A rate-based alert can still fire just after the fault was fixed: same problem.
    inc_id = post_alerts(client, alert("DependencyDown", category="dependency"))[
        "opened_incidents"][0]
    post_alerts(client, alert("DependencyDown", status="resolved", category="dependency"))
    assert client.get(f"/api/incidents/{inc_id}").json()["status"] == "resolved"

    again = post_alerts(client, alert("HighErrorRate"))
    assert again["opened_incidents"] == []
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "open" and inc["resolved_at"] is None
    assert {a["alertname"] for a in inc["alerts"]} == {"DependencyDown", "HighErrorRate"}
    assert "Reopened: HighErrorRate" in inc["notes"][-1]["note"]


def test_alert_after_reopen_window_opens_new_incident(client, monkeypatch):
    import app.incidents
    monkeypatch.setattr(app.incidents, "REOPEN_WINDOW_MIN", 0)
    inc_id = post_alerts(client, alert("HighErrorRate"))["opened_incidents"][0]
    post_alerts(client, alert("HighErrorRate", status="resolved"))
    again = post_alerts(client, alert("HighErrorRate"))
    assert len(again["opened_incidents"]) == 1
    assert again["opened_incidents"][0] != inc_id


def test_baseline_ignores_points_inside_other_incidents():
    from app.incidents import _summarise
    # 0-9: healthy (1%), 10-19: an earlier incident (60%), 20-29: this incident (40%).
    points = [[t, 0.01 if t < 10 else 0.6 if t < 20 else 0.4] for t in range(30)]
    s = _summarise(points, this_start=20, exclude=[[10, 19]])
    assert s["baseline"] == 0.01 and s["baseline_clean"] is True and s["now"] == 0.4
    # Without the exclusion the old first-third rule would be used only as a fallback.
    fallback = _summarise(points, this_start=2, exclude=[[0, 30]])
    assert fallback["baseline_clean"] is False


def test_resolution_for_unknown_alert_is_ignored(client):
    result = post_alerts(client, alert("Unknown", status="resolved"))
    assert result["opened_incidents"] == []
    assert client.get("/api/incidents").json() == []


def test_ground_truth_alert_is_recorded_but_never_opens_incident(client):
    gt = alert("ChaosInjectionActive", severity="info", category="experiment",
               ground_truth="true", mode="error_rate")
    assert post_alerts(client, gt)["opened_incidents"] == []

    inc_id = post_alerts(client, alert("HighErrorRate"))["opened_incidents"][0]
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["ground_truth"][0]["mode"] == "error_rate"
    assert [a["alertname"] for a in inc["alerts"]] == ["HighErrorRate"]


def test_ground_truth_arriving_after_open_attaches(client):
    inc_id = post_alerts(client, alert("HighLatencyP95", severity="warning",
                                       category="latency"))["opened_incidents"][0]
    post_alerts(client, alert("ChaosInjectionActive", severity="info", category="experiment",
                              ground_truth="true", mode="latency_ms", fp="gt-lat"))
    assert client.get(f"/api/incidents/{inc_id}").json()["ground_truth"][0]["mode"] == "latency_ms"


def test_incident_actions(client):
    inc_id = post_alerts(client, alert("HighErrorRate"))["opened_incidents"][0]
    r = client.post(f"/api/incidents/{inc_id}/acknowledge", json={"note": "looking"})
    assert r.json()["status"] == "acknowledged"
    # acknowledged incidents still collect new alerts
    assert post_alerts(client, alert("HighCpuUsage", category="saturation"))[
        "opened_incidents"] == []
    client.post(f"/api/incidents/{inc_id}/resolve")
    inc = client.get(f"/api/incidents/{inc_id}").json()
    assert inc["status"] == "resolved"
    assert inc["notes"][0]["note"] == "looking"
    assert client.post("/api/incidents/999/resolve").status_code == 404
    assert client.post(f"/api/incidents/{inc_id}/explode").status_code == 422


def test_invalid_payload(client):
    assert client.post("/api/alerts/alertmanager", json={"nope": 1}).status_code == 422


def test_evidence_survives_unreachable_upstreams(bare_client):
    inc_id = bare_client.post("/api/alerts/alertmanager",
                              json={"alerts": [alert("DemoAppDown")]}).json()[
        "opened_incidents"][0]
    ev = bare_client.get(f"/api/incidents/{inc_id}").json()["evidence"]
    assert "not configured" in ev["metrics"]["error_ratio"]["error"]
    assert "not configured" in ev["logs"]["error"]
    assert ev["release"]["available"] is False
