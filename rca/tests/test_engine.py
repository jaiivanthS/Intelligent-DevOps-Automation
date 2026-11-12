import json

import numpy as np
import pytest

from rca_engine import CAUSES, RCAEngine
from rca_engine.benchmarks.rcaeval import case_to_evidence, map_columns, parse_case
from rca_engine.causes import CAUSE_KEYS
from rca_engine.evaluate import featurize
from rca_engine.features import FEATURE_NAMES, extract
from rca_engine.live import evaluate as live_evaluate
from rca_engine.model import RCAModel
from rca_engine.rules import predict
from rca_engine.synthetic import dataset, generate, normal_windows


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    ev, al, y = dataset(60, seed=1, difficulty={"standard": 0.7, "hard": 0.3})
    _, X = featurize(ev, al)
    _, Xn = featurize(normal_windows(200, 2), [[]] * 200)
    m = RCAModel.train(X, y, Xn, kind="random_forest", seed=0)
    path = tmp_path_factory.mktemp("m") / "model.joblib"
    m.save(str(path))
    return str(path)


def test_features_complete_and_finite():
    rng = np.random.default_rng(0)
    for cause in (*CAUSE_KEYS, None):
        ev, al = generate(cause, rng, "hard")
        f = extract(ev, al)
        assert list(f) == list(FEATURE_NAMES)
        assert all(np.isfinite(v) for v in f.values())


def test_features_tolerate_empty_and_broken_evidence():
    f = extract({}, None)
    assert f["missing_signals"] == 8 + 1 - 1  # 7 metrics counted + logs; in_flight isn't counted
    f = extract({"metrics": {"error_ratio": {"error": "x"}}, "logs": {"error": "loki down"}}, [])
    assert f["err_now"] == 0 and f["dep_min"] == 1


def test_ground_truth_alerts_are_never_features():
    alerts = [{"category": "experiment", "labels": {"ground_truth": "true"}},
              {"category": "errors", "labels": {"ground_truth": "true"}}]
    f = extract({}, alerts)
    assert f["alert_errors"] == 0


def test_rules_on_clear_cases():
    rng = np.random.default_rng(3)
    for cause in ("dependency_failure", "service_down", "bad_deployment"):
        hits = sum(predict(extract(*generate(cause, rng))) == cause for _ in range(40))
        assert hits >= 32, cause


def test_rules_use_dependency_logs_when_metric_missing():
    ev = {"metrics": {"error_ratio": {"now": 0.5, "baseline": 0.0, "max": 0.5, "points": []},
                      "dependency_up": {"error": "not exported"}},
          "logs": {"error_lines": 80, "events": {},
                   "top_messages": [{"msg": "inventory-db connection refused", "count": 80}]}}
    assert predict(extract(ev, [])) == "dependency_failure"


def test_engine_with_model_explains_and_suggests(model):
    engine = RCAEngine.load(model)
    assert engine.model is not None
    ev, al = generate("dependency_failure", np.random.default_rng(11))
    r = engine.analyze(ev, al)
    assert r["top_cause"] == "dependency_failure"
    assert 0 < r["confidence"] <= 1
    assert r["ranking"][0]["cause"] == "dependency_failure" and len(r["ranking"]) == 4
    assert any("dependency" in e.lower() for e in r["evidence"])
    assert r["suggested_checks"] == list(CAUSES["dependency_failure"].checks)
    assert r["suggested_action"] == "none"
    assert r["anomaly"]["top_deviations"]
    json.dumps(r)  # must be JSON-serialisable for the platform DB


def test_rollback_only_suggested_when_last_good_exists(model):
    engine = RCAEngine.load(model)
    ev, al = generate("bad_deployment", np.random.default_rng(5))
    assert engine.analyze(ev, al)["suggested_action"] == "rollback"
    ev["release"] = {"current_image": "x", "last_good_image": None}
    assert engine.analyze(ev, al)["suggested_action"] == "none"


def test_missing_model_falls_back_to_rules(tmp_path):
    engine = RCAEngine.load(str(tmp_path / "nope.joblib"))
    assert engine.model is None and engine.name == "rule-based baseline"
    r = engine.analyze(*generate("service_down", np.random.default_rng(1)))
    assert r["top_cause"] == "service_down" and r["anomaly"] is None


def test_corrupt_model_falls_back_to_rules(tmp_path):
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a model")
    assert RCAEngine.load(str(bad)).model is None


def test_model_beats_chance_on_hard_holdout(model):
    m = RCAModel.load(model)
    ev, al, y = dataset(20, seed=99, difficulty="hard")
    _, X = featurize(ev, al)
    ac1 = np.mean([r[0] == t for r, t in zip(m.rank_many(X), y, strict=True)])
    assert ac1 > 0.7  # chance is 1/7


def test_anomaly_threshold_calibrated(model):
    m = RCAModel.load(model)
    _, Xn = featurize(normal_windows(200, 77), [[]] * 200)
    assert m.is_anomalous_many(Xn).mean() < 0.1


# ------------------------------------------------------------------ RCAEval
def test_rcaeval_case_parsing_and_mapping():
    assert parse_case("re1ob_adservice_cpu_1") == {"bench": "re1ob", "service": "adservice",
                                                  "fault": "cpu", "inst": "1"}
    assert parse_case("re2tt_ts-auth-service_socket_3")["service"] == "ts-auth-service"
    cols = ["time", "adservice_cpu", "adservice_mem", "adservice_latency-90", "cartservice_cpu"]
    assert map_columns(cols, "adservice") == {"cpu_cores": "adservice_cpu",
                                              "memory_rss_bytes": "adservice_mem",
                                              "latency_p95": "adservice_latency-90"}


def test_rcaeval_case_to_evidence(tmp_path):
    pd = pytest.importorskip("pandas")
    case = tmp_path / "re1ob_adservice_cpu_1"
    case.mkdir()
    t0 = 1_692_569_339
    times = np.arange(t0 - 1800, t0 + 600, 15)
    cpu = np.where(times >= t0, 0.95, 0.1)
    pd.DataFrame({"time": times, "adservice_cpu": cpu, "adservice_latency": 0.05,
                  "cartservice_cpu": 0.2}).to_csv(case / "data.csv", index=False)
    (case / "inject_time.txt").write_text(str(t0))
    ev, cause, mapping = case_to_evidence(case)
    assert cause == "cpu_saturation"
    assert mapping["cpu_cores"] == "adservice_cpu"
    assert ev["metrics"]["cpu_cores"]["baseline"] == pytest.approx(0.1)
    assert extract(ev, [])["cpu_now"] == pytest.approx(0.95)
    skipped = tmp_path / "re1ob_adservice_disk_1"
    skipped.mkdir()
    assert case_to_evidence(skipped) is None


# ---------------------------------------------------------------- live eval
def test_live_evaluate(tmp_path, model):
    rng = np.random.default_rng(8)
    rows = []
    for cause in ("memory_leak", "dependency_failure"):
        ev, al = generate(cause, rng)
        rows.append(json.dumps({"id": 1, "cause": cause, "evidence": ev, "alerts": al}))
    data = tmp_path / "live.jsonl"
    data.write_text("\n".join(rows))
    r = live_evaluate(str(data), model)
    assert r["incidents"] == 2 and "rule_based" in r and "model" in r
