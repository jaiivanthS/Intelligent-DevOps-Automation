"""RCAEval benchmark adapter (Pham et al., "RCAEval: A Benchmark for Root Cause
Analysis of Microservice Systems with Telemetry Data", 2025).

Source: https://github.com/phamquiluan/RCAEval. Code is MIT-licensed. The
datasets are stated as MIT in the README and CC BY 4.0 on Zenodo
(record 14590730). Cite the paper and give attribution when you report results.

TASK MAPPING (important). RCAEval primarily asks *which service* caused a fault.
This platform manages one service and asks *what kind* of fault it is. The
adapter therefore evaluates **fault-type classification on the true root-cause
service's metrics**. That is a related but different task, so never compare
these numbers with RCAEval's published localisation scores (Avg@5, etc.).

Fault-type mapping (our assumption, applied to RE1/RE2 resource and network faults):
    cpu -> cpu_saturation, mem -> memory_leak, delay -> latency_degradation,
    loss -> latency_degradation (retransmissions), socket -> dependency_failure.
    disk and the RE3 code-level faults (f1..f5) have no matching class and are skipped.

SCHEMA CAVEAT. RCAEval documents only a `time` column plus per-case
`inject_time.txt`. Metric column names are not specified. Columns are matched
to our metrics with the regexes in `COLUMN_PATTERNS`. Run with `--inspect` on
the downloaded data and adjust the patterns before you trust any result.

Usage (needs `pip install -e ".[benchmark]"` and the downloaded data, about 5 GB zipped):
    python -m rca_engine.benchmarks.rcaeval --data data/RE2 --inspect
    python -m rca_engine.benchmarks.rcaeval --data data/RE2 --model models/rca_model.joblib
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

FAULT_TO_CAUSE = {
    "cpu": "cpu_saturation",
    "mem": "memory_leak",
    "delay": "latency_degradation",
    "loss": "latency_degradation",
    "socket": "dependency_failure",
}

# our metric name -> regex applied to the column suffix after "<service>_"
COLUMN_PATTERNS: dict[str, str] = {
    "cpu_cores": r"cpu",
    "memory_rss_bytes": r"mem|memory|rss|working_set",
    "latency_p95": r"lat|latency|duration|response_time",
    "error_ratio": r"err|error|5xx|fail",
    "request_rate": r"load|rps|requests?|throughput|qps|count",
}

CASE_RE = re.compile(r"^(?P<bench>[a-z0-9]+)_(?P<service>.+)_(?P<fault>[a-z0-9]+)_(?P<inst>\d+)$",
                     re.I)
BASELINE_MIN = 25
POST_MIN = 5


def parse_case(name: str) -> dict[str, str] | None:
    """`re1ob_adservice_cpu_1` -> bench, service, fault, instance."""
    m = CASE_RE.match(name)
    return m.groupdict() if m else None


def load_metrics(case_dir: Path):
    import pandas as pd  # optional dependency

    for fname, reader in (("metrics.parquet", pd.read_parquet), ("metrics.csv", pd.read_csv),
                          ("data.csv", pd.read_csv), ("metrics.json", pd.read_json)):
        path = case_dir / fname
        if path.exists():
            df = reader(path)
            if "time" not in df.columns:
                raise ValueError(f"{path}: no 'time' column")
            return df.sort_values("time").reset_index(drop=True)
    raise FileNotFoundError(f"no metrics file in {case_dir}")


def map_columns(columns: list[str], service: str) -> dict[str, str]:
    """Pick one column per metric among `<service>_*` columns (first match wins)."""
    prefix = service.lower() + "_"
    candidates = [c for c in columns if c.lower().startswith(prefix)]
    mapping: dict[str, str] = {}
    for metric, pattern in COLUMN_PATTERNS.items():
        for col in candidates:
            if re.search(pattern, col[len(prefix):], re.I) and col not in mapping.values():
                mapping[metric] = col
                break
    return mapping


def case_to_evidence(case_dir: Path) -> tuple[dict[str, Any], str, dict[str, str]] | None:
    """Return (evidence, cause label, column mapping), or None if the fault type is unsupported."""
    info = parse_case(case_dir.name)
    if not info or info["fault"].lower() not in FAULT_TO_CAUSE:
        return None
    df = load_metrics(case_dir)
    t0 = float((case_dir / "inject_time.txt").read_text().strip())
    # RCAEval timestamps are Unix seconds; tolerate milliseconds.
    if df["time"].max() > 1e12:
        df["time"] = df["time"] / 1000.0
    window = df[(df["time"] >= t0 - BASELINE_MIN * 60) & (df["time"] <= t0 + POST_MIN * 60)]
    mapping = map_columns(list(df.columns), info["service"])

    metrics: dict[str, Any] = {}
    for metric in ("error_ratio", "latency_p95", "request_rate", "memory_rss_bytes", "cpu_cores",
                   "in_flight", "dependency_up", "up"):
        col = mapping.get(metric)
        if not col:
            metrics[metric] = {"error": "not in benchmark"}
            continue
        series = window[["time", col]].dropna()
        values = series[col].astype(float).tolist()
        if not values:
            metrics[metric] = {"error": "no data in window"}
            continue
        before = series[series["time"] < t0][col].astype(float)
        metrics[metric] = {
            "now": values[-1],
            "baseline": float(before.median()) if len(before) else values[0],
            "max": max(values),
            "points": [[float(t), float(v)] for t, v in zip(series["time"], values, strict=True)],
        }
    evidence = {"collected_at": None, "metrics": metrics,
                "logs": {"error": "logs not used for RCAEval"}, "deployments": []}
    return evidence, FAULT_TO_CAUSE[info["fault"].lower()], mapping


def iter_cases(root: Path):
    yield from sorted(p for p in root.rglob("*") if p.is_dir() and (p / "inject_time.txt").exists())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="directory containing RCAEval case directories")
    ap.add_argument("--model", help="trained model (omit for rule-based baseline only)")
    ap.add_argument("--inspect", action="store_true", help="only show discovered column mappings")
    ap.add_argument("--out", default="reports/rcaeval_evaluation.json")
    args = ap.parse_args()

    from ..engine import RCAEngine
    from ..features import extract
    from ..rules import rank as rule_rank

    engine = RCAEngine.load(args.model) if args.model else None
    rows, skipped = [], 0
    for case in iter_cases(Path(args.data)):
        converted = case_to_evidence(case)
        if converted is None:
            skipped += 1
            continue
        evidence, cause, mapping = converted
        if args.inspect:
            print(f"{case.name:45s} -> {cause:22s} {json.dumps(mapping)}")
            continue
        f = extract(evidence, [])
        row = {"case": case.name, "cause": cause, "mapped": sorted(mapping),
               "rule_ranking": [c for c, _ in rule_rank(f)]}
        if engine and engine.model:
            row["model_ranking"] = [c for c, _ in engine.model.rank(f)]
        rows.append(row)

    if args.inspect:
        print(f"skipped (unsupported fault types): {skipped}")
        return
    summary = {"cases": len(rows), "skipped_unsupported": skipped}
    for key in ("rule_ranking", "model_ranking"):
        scored = [r for r in rows if key in r]
        if scored:
            summary[key.replace("_ranking", "")] = {
                "ac1": sum(r[key][0] == r["cause"] for r in scored) / len(scored),
                "ac3": sum(r["cause"] in r[key][:3] for r in scored) / len(scored),
            }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
