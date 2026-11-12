"""Live-demo evaluation: incidents created by real fault injection on the platform.

Every incident during which a fault was injected carries `ground_truth` (from the
ChaosInjectionActive alert). That gives labelled, real-telemetry incidents.

    # 1. export labelled incidents from a running platform
    python -m rca_engine.live export --api http://<app_ip>:8000 --out data/live.jsonl
    # 2. evaluate the rule-based baseline and a trained model on them
    python -m rca_engine.live evaluate --data data/live.jsonl --model models/rca_model.joblib

Report these numbers separately from the synthetic and RCAEval results.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import Counter
from pathlib import Path

from .causes import CHAOS_MODE_TO_CAUSE
from .engine import RCAEngine
from .features import extract
from .rules import rank as rule_rank


def _get(url: str):
    if not url.startswith(("http://", "https://")):
        raise ValueError("API URL must be http(s)")
    # Scheme restricted to http(s) just above.
    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310  # nosec B310
        return json.loads(resp.read())


def export(api: str, out: str) -> int:
    api = api.rstrip("/")
    n = 0
    lines = []
    for summary in _get(f"{api}/api/incidents?limit=500"):
        inc = _get(f"{api}/api/incidents/{summary['id']}")
        modes = {g.get("mode") for g in inc.get("ground_truth") or []} - {None}
        causes = {CHAOS_MODE_TO_CAUSE[m] for m in modes if m in CHAOS_MODE_TO_CAUSE}
        if len(causes) != 1 or not inc.get("evidence"):
            continue  # unlabelled or ambiguous (several faults at once)
        lines.append(json.dumps({"id": inc["id"], "cause": causes.pop(),
                                 "evidence": inc["evidence"], "alerts": inc["alerts"]}))
        n += 1
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return n


def evaluate(data: str, model: str | None) -> dict:
    rows = [json.loads(line) for line in Path(data).read_text(encoding="utf-8").splitlines() if line]
    engine = RCAEngine.load(model) if model else RCAEngine(None)
    result: dict = {"incidents": len(rows), "by_cause": dict(Counter(r["cause"] for r in rows))}
    for name, ranker in (("rule_based", lambda f: [c for c, _ in rule_rank(f)]),
                         ("model", (lambda f: [c for c, _ in engine.model.rank(f)])
                          if engine.model else None)):
        if ranker is None or not rows:
            continue
        ranked = [ranker(extract(r["evidence"], r["alerts"])) for r in rows]
        result[name] = {
            "ac1": sum(rk[0] == r["cause"] for rk, r in zip(ranked, rows, strict=True)) / len(rows),
            "ac3": sum(r["cause"] in rk[:3] for rk, r in zip(ranked, rows, strict=True)) / len(rows),
        }
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--api", required=True)
    e.add_argument("--out", default="data/live.jsonl")
    v = sub.add_parser("evaluate")
    v.add_argument("--data", required=True)
    v.add_argument("--model")
    v.add_argument("--out", default="reports/live_evaluation.json")
    args = ap.parse_args()
    if args.cmd == "export":
        print(f"exported {export(args.api, args.out)} labelled incidents to {args.out}")
    else:
        result = evaluate(args.data, args.model)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
