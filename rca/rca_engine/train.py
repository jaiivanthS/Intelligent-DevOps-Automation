"""Train the production RCA model and save it.

    python -m rca_engine.train --out models/rca_model.joblib [--kind random_forest]

Trains on synthetic incidents (70% standard / 30% hard), plus live labelled
incidents if --live JSONL is given (exported with scripts/export_live_incidents.py).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .evaluate import TRAIN_MIX, featurize
from .model import RCAModel
from .synthetic import dataset, normal_windows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="models/rca_model.joblib")
    ap.add_argument("--kind", default="random_forest",
                    choices=["random_forest", "gradient_boosting", "xgboost"])
    ap.add_argument("--n-per-class", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--live", help="JSONL of labelled live incidents to add to training")
    args = ap.parse_args()

    ev, al, y = dataset(args.n_per_class, args.seed, TRAIN_MIX)
    n_live = 0
    if args.live:
        for line in Path(args.live).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            ev.append(row["evidence"])
            al.append(row.get("alerts") or [])
            y.append(row["cause"])
            n_live += 1
    _, X = featurize(ev, al)
    _, X_normal = featurize(normal_windows(1000, args.seed + 1), [[]] * 1000)

    model = RCAModel.train(X, y, X_normal, kind=args.kind, seed=args.seed, meta={
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_synthetic": len(y) - n_live, "n_live": n_live, "seed": args.seed,
        "class_counts": {c: int(n) for c, n in zip(*np.unique(y, return_counts=True), strict=True)},
    })
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    model.save(args.out)
    print(f"saved {args.kind} model ({len(y)} incidents, {n_live} live) to {args.out}")


if __name__ == "__main__":
    main()
