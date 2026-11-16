"""Export the RCA datasets as CSV files that open in Excel.

    cd rca
    python scripts/export_dataset.py                       # synthetic only
    python scripts/export_dataset.py --api http://localhost:8081 --model models/rca_model.joblib

Writes (in rca/data/):
  synthetic_training_dataset.csv  exactly the training set of models/rca_model.joblib:
                                  500 incidents per cause (7 causes, seed 42, 70% standard /
                                  30% hard) + 1000 normal windows (label "normal")
  live.jsonl                      labelled incidents exported from the running platform
                                  (full evidence: metrics, logs, deployments, alerts)
  live_incidents.csv              the same incidents as features + true cause + what the
                                  model and the rule baseline predicted
Column meanings: rca/data/README.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rca_engine.engine import RCAEngine  # noqa: E402
from rca_engine.evaluate import TRAIN_MIX, featurize  # noqa: E402
from rca_engine.features import FEATURE_NAMES  # noqa: E402
from rca_engine.live import export as live_export  # noqa: E402
from rca_engine.live import features_of  # noqa: E402
from rca_engine.rules import rank as rule_rank  # noqa: E402
from rca_engine.synthetic import dataset, normal_windows  # noqa: E402

N_PER_CLASS = 500   # same defaults as rca_engine.train
N_NORMAL = 1000
SEED = 42


def _num(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(float(v), 6)


def export_synthetic(out: Path) -> int:
    ev, al, y = dataset(N_PER_CLASS, SEED, TRAIN_MIX)
    feats, _ = featurize(ev, al)
    normal = normal_windows(N_NORMAL, SEED + 1)
    nfeats, _ = featurize(normal, [[]] * N_NORMAL)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_id", "label", "is_incident", *FEATURE_NAMES])
        row = 0
        for f, label in zip(feats, y, strict=True):
            row += 1
            w.writerow([row, label, 1, *(_num(f[k]) for k in FEATURE_NAMES)])
        for f in nfeats:
            row += 1
            w.writerow([row, "normal", 0, *(_num(f[k]) for k in FEATURE_NAMES)])
    return row


def export_live(api: str, jsonl: Path, out: Path, model: str | None) -> int:
    n = live_export(api, str(jsonl))
    engine = RCAEngine.load(model) if model else RCAEngine(None)
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line]
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["incident_id", "true_cause", "model_prediction", "model_confidence",
                    "rule_prediction", "model_correct", "rule_correct", "alerts",
                    "features_source", *FEATURE_NAMES])
        for r in rows:
            f = features_of(r)
            stored = r.get("rca_features") or {}
            source = "as_analysed" if all(k in stored for k in FEATURE_NAMES) else "re_extracted"
            ranked = engine.model.rank(f) if engine.model else rule_rank(f)
            rule_top = rule_rank(f)[0][0]
            w.writerow([r["id"], r["cause"], ranked[0][0], round(ranked[0][1], 3), rule_top,
                        int(ranked[0][0] == r["cause"]), int(rule_top == r["cause"]),
                        ";".join(sorted({a["alertname"] for a in r["alerts"]})), source,
                        *(_num(f[k]) for k in FEATURE_NAMES)])
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", help="platform URL for the live export, e.g. http://localhost:8081")
    ap.add_argument("--model", default=str(ROOT / "models" / "rca_model.joblib"))
    ap.add_argument("--outdir", default=str(ROOT / "data"))
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    n = export_synthetic(outdir / "synthetic_training_dataset.csv")
    print(f"synthetic: {n} rows -> {outdir / 'synthetic_training_dataset.csv'}")
    if args.api:
        model = args.model if Path(args.model).exists() else None
        n = export_live(args.api, outdir / "live.jsonl", outdir / "live_incidents.csv", model)
        print(f"live: {n} labelled incidents -> {outdir / 'live_incidents.csv'} "
              f"(model: {'trained' if model else 'rule baseline only'})")


if __name__ == "__main__":
    main()
