import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import alert, handler, make_settings

rca_engine = pytest.importorskip("rca_engine")


def open_incident(client) -> int:
    r = client.post("/api/alerts/alertmanager", json={"alerts": [alert("HighErrorRate")]})
    return r.json()["opened_incidents"][0]


def test_rca_runs_after_evidence_with_rule_fallback(client):
    assert client.get("/api/config").json()["rca"] == "rule-based baseline"
    inc = client.get(f"/api/incidents/{open_incident(client)}").json()
    rca = inc["rca"]
    # fake upstreams: error ratio 0 -> 60%, application-failure logs, no recent deploy
    assert rca["top_cause"] == "error_burst"
    assert rca["model"] == "rule-based baseline"
    assert any("error ratio rose" in e for e in rca["evidence"])
    assert rca["suggested_checks"]
    assert rca["analyzed_at"]
    listed = client.get("/api/incidents").json()[0]
    assert listed["has_rca"] == 1


def test_rerun_rca_endpoint(client):
    inc_id = open_incident(client)
    r = client.post(f"/api/incidents/{inc_id}/rca")
    assert r.status_code == 200 and r.json()["top_cause"] == "error_burst"
    assert client.post("/api/incidents/999/rca").status_code == 404


def test_rca_with_trained_model(tmp_path):
    from rca_engine.evaluate import featurize
    from rca_engine.model import RCAModel
    from rca_engine.synthetic import dataset, normal_windows

    ev, al, y = dataset(40, seed=3)
    _, X = featurize(ev, al)
    _, Xn = featurize(normal_windows(100, 4), [[]] * 100)
    path = tmp_path / "m.joblib"
    RCAModel.train(X, y, Xn, seed=0).save(str(path))

    (tmp_path / "state").mkdir()
    app = create_app(make_settings(tmp_path, rca_model_path=str(path)),
                     transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        assert c.get("/api/config").json()["rca"] == "random_forest + isolation forest"
        rca = c.get(f"/api/incidents/{open_incident(c)}").json()["rca"]
        assert rca["model"] == "random_forest + isolation forest"
        assert len(rca["ranking"]) == 4
        assert rca["anomaly"]["top_deviations"]
        assert rca["rule_based"]["top_cause"]
