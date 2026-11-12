"""Compare RCA methods on synthetic incidents.

    python -m rca_engine.evaluate --out-dir reports

Methods: rule-based baseline, Random Forest, gradient boosting (sklearn
HistGradientBoosting), XGBoost (if installed). Test sets: held-out "standard"
incidents and a distribution-shifted "hard" set (weaker signals, more missing
telemetry, more confounding deployments). Also: feature-group ablations and
Isolation Forest anomaly-detection AUC.

Metrics: AC@1 / AC@3 (true cause ranked first / in the top 3), macro-F1,
per-class recall, confusion matrix.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score, roc_auc_score

from . import rules
from .causes import CAUSE_KEYS
from .features import FEATURE_NAMES, extract, to_vector
from .model import RCAModel
from .synthetic import dataset, normal_windows

TRAIN_MIX = {"standard": 0.7, "hard": 0.3}
GROUPS = {
    "logs": [n for n in FEATURE_NAMES if n.startswith("log_")],
    "deploy": ["mins_since_deploy", "recent_deploy", "recent_rollback"],
    "alerts": [n for n in FEATURE_NAMES if n.startswith("alert_")],
}


def featurize(evidences, alerts) -> tuple[list[dict], np.ndarray]:
    feats = [extract(e, a) for e, a in zip(evidences, alerts, strict=True)]
    return feats, np.array([to_vector(f) for f in feats])


def scores(ranked: list[list[str]], labels: list[str]) -> dict:
    top1 = [r[0] for r in ranked]
    ac1 = float(np.mean([r[0] == y for r, y in zip(ranked, labels, strict=True)]))
    ac3 = float(np.mean([y in r[:3] for r, y in zip(ranked, labels, strict=True)]))
    recall = {c: float(np.mean([p == c for p, y in zip(top1, labels, strict=True) if y == c]))
              for c in CAUSE_KEYS}
    return {"ac1": ac1, "ac3": ac3,
            "macro_f1": float(f1_score(labels, top1, labels=list(CAUSE_KEYS), average="macro")),
            "recall": recall,
            "confusion": confusion_matrix(labels, top1, labels=list(CAUSE_KEYS)).tolist()}


def run(n_train: int, n_test: int, seed: int, include_xgboost: bool) -> dict:
    t0 = time.time()
    ev, al, y_train = dataset(n_train, seed, TRAIN_MIX)
    _, X_train = featurize(ev, al)
    _, X_normal = featurize(normal_windows(800, seed + 1), [[]] * 800)

    tests = {}
    for name, diff, s in (("standard", "standard", seed + 2), ("hard", "hard", seed + 3)):
        e, a, y = dataset(n_test, s, diff)
        feats, X = featurize(e, a)
        tests[name] = (feats, X, y)

    kinds = ["random_forest", "gradient_boosting"]
    if include_xgboost:
        try:
            import xgboost  # noqa: F401

            kinds.append("xgboost")
        except ImportError:
            pass

    results: dict = {"methods": {}, "ablation": {}, "anomaly": {}}
    results["methods"]["rule_based"] = {
        name: scores([[c for c, _ in rules.rank(f)] for f in feats], y)
        for name, (feats, _, y) in tests.items()}

    models = {}
    for kind in kinds:
        m = RCAModel.train(X_train, y_train, X_normal, kind=kind, seed=seed)
        models[kind] = m
        results["methods"][kind] = {name: scores(m.rank_many(X), y)
                                    for name, (_, X, y) in tests.items()}

    # Ablations (Random Forest): which evidence sources matter?
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    variants = {
        "all features": list(FEATURE_NAMES),
        "without logs": [n for n in FEATURE_NAMES if n not in GROUPS["logs"]],
        "without deploy context": [n for n in FEATURE_NAMES if n not in GROUPS["deploy"]],
        "without alert labels": [n for n in FEATURE_NAMES if n not in GROUPS["alerts"]],
        "metrics only": [n for n in FEATURE_NAMES
                         if n not in GROUPS["logs"] + GROUPS["deploy"] + GROUPS["alerts"]],
    }
    for label, cols in variants.items():
        ci = [idx[c] for c in cols]
        clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                                     class_weight="balanced", random_state=seed, n_jobs=-1)
        clf.fit(X_train[:, ci], y_train)
        out = {}
        for name, (_, X, y) in tests.items():
            proba = clf.predict_proba(X[:, ci])
            ranked = [[clf.classes_[j] for j in row] for row in np.argsort(-proba, axis=1)]
            s = scores(ranked, y)
            out[name] = {"ac1": s["ac1"], "ac3": s["ac3"], "macro_f1": s["macro_f1"]}
        results["ablation"][label] = out

    # Anomaly detection: Isolation Forest on unseen normal windows vs incidents.
    _, X_norm_test = featurize(normal_windows(300, seed + 4), [[]] * 300)
    m = models["random_forest"]
    for name, (_, X, _) in tests.items():
        s_inc = -m.detector.score_samples(X)
        s_norm = -m.detector.score_samples(X_norm_test)
        labels = np.r_[np.ones(len(s_inc)), np.zeros(len(s_norm))]
        results["anomaly"][name] = {
            "auc": float(roc_auc_score(labels, np.r_[s_inc, s_norm])),
            "flagged_incidents": float(np.mean(m.is_anomalous_many(X))),
            "false_alarm_rate": float(np.mean(m.is_anomalous_many(X_norm_test))),
        }

    results["importances"] = sorted(models["random_forest"].importances().items(),
                                    key=lambda kv: kv[1], reverse=True)[:12]
    results["setup"] = {"n_train": n_train * len(CAUSE_KEYS), "n_test_per_set": n_test * len(CAUSE_KEYS),
                        "n_normal_train": 800, "train_mix": TRAIN_MIX, "seed": seed,
                        "features": len(FEATURE_NAMES), "classes": list(CAUSE_KEYS),
                        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        "runtime_s": round(time.time() - t0, 1)}
    return results


def to_markdown(r: dict) -> str:
    pct = lambda v: f"{100 * v:.1f}%"  # noqa: E731
    s = r["setup"]
    lines = [
        "# RCA evaluation: synthetic incidents",
        "",
        "> **Scope.** These results use *synthetic* incidents from `rca_engine/synthetic.py`.",
        "> They measure how the methods compare under controlled conditions. They do **not**",
        "> predict production accuracy. Benchmark (RCAEval) and live-demo results are reported",
        "> separately (see `README.md`).",
        ">",
        "> **Why the ML scores are so high.** The generator ties each cause to signals that the",
        "> features measure directly, so the classes separate well. Treat the *relative* order of",
        "> the methods, the per-cause gaps and the ablations as the findings. The absolute",
        "> accuracy is not a finding. The rule-based baseline uses hand-set thresholds that were",
        "> not tuned on this data.",
        "",
        f"Train: {s['n_train']} incidents (70% standard / 30% hard), {s['n_normal_train']} "
        f"normal windows. Test: {s['n_test_per_set']} incidents per set. "
        f"{s['features']} features, {len(s['classes'])} causes, seed {s['seed']}. "
        f"Generated {s['generated_at']}.",
        "",
        "## Cause ranking",
        "",
        "| Method | AC@1 standard | AC@3 standard | Macro-F1 standard "
        "| AC@1 hard | AC@3 hard | Macro-F1 hard |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, res in r["methods"].items():
        st, hd = res["standard"], res["hard"]
        lines.append(f"| {name.replace('_', ' ')} | {pct(st['ac1'])} | {pct(st['ac3'])} | "
                     f"{pct(st['macro_f1'])} | {pct(hd['ac1'])} | {pct(hd['ac3'])} | "
                     f"{pct(hd['macro_f1'])} |")
    best = max((k for k in r["methods"] if k != "rule_based"),
               key=lambda k: r["methods"][k]["hard"]["ac1"])
    lines += ["", f"## Per-cause recall (hard set): rule-based vs {best.replace('_', ' ')}", "",
              "| Cause | Rule-based | " + best.replace("_", " ") + " |", "|---|---|---|"]
    for c in s["classes"]:
        lines.append(f"| {c} | {pct(r['methods']['rule_based']['hard']['recall'][c])} | "
                     f"{pct(r['methods'][best]['hard']['recall'][c])} |")
    lines += ["", f"## Confusion matrix ({best.replace('_', ' ')}, hard set)", "",
              "Rows = true cause, columns = predicted.", "",
              "| true \\ pred | " + " | ".join(c[:10] for c in s["classes"]) + " |",
              "|---" * (len(s["classes"]) + 1) + "|"]
    for c, row in zip(s["classes"], r["methods"][best]["hard"]["confusion"], strict=True):
        lines.append(f"| {c} | " + " | ".join(str(v) for v in row) + " |")
    lines += ["", "## Ablation (Random Forest): which evidence matters", "",
              "| Features | AC@1 standard | AC@1 hard | Macro-F1 hard |", "|---|---|---|---|"]
    for label, res in r["ablation"].items():
        lines.append(f"| {label} | {pct(res['standard']['ac1'])} | {pct(res['hard']['ac1'])} | "
                     f"{pct(res['hard']['macro_f1'])} |")
    lines += ["", "## Anomaly detection (Isolation Forest, trained on normal windows only)", "",
              "| Test set | ROC AUC | Incidents flagged | False alarms on normal windows |",
              "|---|---|---|---|"]
    for name, a in r["anomaly"].items():
        lines.append(f"| {name} | {a['auc']:.3f} | {pct(a['flagged_incidents'])} | "
                     f"{pct(a['false_alarm_rate'])} |")
    lines += ["", "## Most important features (Random Forest)", "",
              "| Feature | Importance |", "|---|---|"]
    lines += [f"| `{k}` | {v:.3f} |" for k, v in r["importances"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-train", type=int, default=400, help="incidents per cause")
    ap.add_argument("--n-test", type=int, default=150, help="incidents per cause per test set")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--xgboost", action="store_true", help="include XGBoost if installed")
    ap.add_argument("--out-dir", default="reports")
    args = ap.parse_args()

    r = run(args.n_train, args.n_test, args.seed, args.xgboost)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "synthetic_evaluation.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (out / "synthetic_evaluation.md").write_text(to_markdown(r), encoding="utf-8")
    print(to_markdown(r))


if __name__ == "__main__":
    main()
