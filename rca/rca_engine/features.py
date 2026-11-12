"""Feature extraction from an incident evidence snapshot.

The SAME function is used for training (on synthetic or benchmark evidence)
and at serving time (on the platform's real evidence), so there is no
train/serve skew. Input format = platform `incidents.evidence`:

    {"collected_at": iso, "metrics": {name: {"now", "baseline", "max", "points": [[t, v], ...]}
                                      | {"error": "..."}},
     "logs": {"error_lines", "top_messages": [{"msg", "level", "count"}], "events": {...}}
             | {"error": "..."},
     "deployments": [{"ts", "event", "status", "image_tag"}], ...}

Missing data is imputed with neutral values and counted in `missing_signals`.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

FEATURE_NAMES: tuple[str, ...] = (
    "err_now", "err_max", "err_delta",
    "lat_now", "lat_log_ratio",
    "rps_log_ratio",
    "mem_log_ratio", "mem_growth_per_min",
    "cpu_now", "cpu_delta",
    "inflight_max",
    "dep_min", "up_min",
    "log_error_lines", "log_dependency_frac", "log_timeout_frac", "log_app_error_frac",
    "mins_since_deploy", "recent_deploy", "recent_rollback",
    "alert_errors", "alert_latency", "alert_saturation", "alert_dependency", "alert_availability",
    "missing_signals",
)

_DEP = re.compile(r"connection refused|unavailable|unreachable|database|\bdb\b|dns|reset by peer|"
                  r"no route to host|dependency", re.I)
_TIMEOUT = re.compile(r"timeout|timed out|deadline exceeded|slow", re.I)
_APP = re.compile(r"exception|traceback|internal server error|failure|failed|panic", re.I)

DEPLOY_WINDOW_MIN = 120.0  # cap for "minutes since last deploy"
RECENT_DEPLOY_MIN = 20.0


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _metric(evidence: dict, name: str) -> dict[str, Any] | None:
    m = (evidence.get("metrics") or {}).get(name)
    if not m or "error" in m:
        return None
    return m


def _values(m: dict[str, Any]) -> list[float]:
    pts = m.get("points") or []
    vals = [float(v) for _, v in pts if v is not None and not math.isnan(float(v))]
    if not vals and m.get("now") is not None:
        vals = [float(m["now"])]
    return vals


def _slope_per_min(m: dict[str, Any]) -> float:
    """Least-squares slope over the most recent half of the window, in units/minute."""
    pts = [(float(t), float(v)) for t, v in (m.get("points") or []) if v is not None]
    pts = pts[len(pts) // 2:]
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    mt = sum(t for t, _ in pts) / n
    mv = sum(v for _, v in pts) / n
    var = sum((t - mt) ** 2 for t, _ in pts)
    if var == 0:
        return 0.0
    return sum((t - mt) * (v - mv) for t, v in pts) / var * 60.0


def _log_ratio(a: float, b: float, eps: float) -> float:
    return math.log((max(a, 0.0) + eps) / (max(b, 0.0) + eps))


def extract(evidence: dict[str, Any], alerts: list[dict[str, Any]] | None = None
            ) -> dict[str, float]:
    f: dict[str, float] = {}
    missing = 0

    # --- errors
    m = _metric(evidence, "error_ratio")
    if m:
        vals = _values(m)
        base = m.get("baseline") if m.get("baseline") is not None else (vals[0] if vals else 0.0)
        now = vals[-1] if vals else 0.0
        f["err_now"], f["err_max"], f["err_delta"] = now, max(vals or [0.0]), now - base
    else:
        missing += 1
        f["err_now"] = f["err_max"] = f["err_delta"] = 0.0

    # --- latency
    m = _metric(evidence, "latency_p95")
    if m:
        vals = _values(m)
        base = m.get("baseline") if m.get("baseline") is not None else (vals[0] if vals else 0.0)
        f["lat_now"] = vals[-1] if vals else 0.0
        f["lat_log_ratio"] = _log_ratio(max(vals or [0.0]), base, 0.01)
    else:
        missing += 1
        f["lat_now"] = f["lat_log_ratio"] = 0.0

    # --- traffic
    m = _metric(evidence, "request_rate")
    if m:
        vals = _values(m)
        base = m.get("baseline") if m.get("baseline") is not None else (vals[0] if vals else 0.0)
        f["rps_log_ratio"] = _log_ratio(vals[-1] if vals else 0.0, base, 0.1)
    else:
        missing += 1
        f["rps_log_ratio"] = 0.0

    # --- memory (relative growth so service size doesn't matter)
    m = _metric(evidence, "memory_rss_bytes")
    if m:
        vals = _values(m)
        base = m.get("baseline") if m.get("baseline") is not None else (vals[0] if vals else 0.0)
        f["mem_log_ratio"] = _log_ratio(vals[-1] if vals else 0.0, base, 1e6)
        f["mem_growth_per_min"] = _slope_per_min(m) / max(base, 1e6)
    else:
        missing += 1
        f["mem_log_ratio"] = f["mem_growth_per_min"] = 0.0

    # --- cpu
    m = _metric(evidence, "cpu_cores")
    if m:
        vals = _values(m)
        base = m.get("baseline") if m.get("baseline") is not None else (vals[0] if vals else 0.0)
        f["cpu_now"] = vals[-1] if vals else 0.0
        f["cpu_delta"] = f["cpu_now"] - base
    else:
        missing += 1
        f["cpu_now"] = f["cpu_delta"] = 0.0

    m = _metric(evidence, "in_flight")
    f["inflight_max"] = max(_values(m) or [0.0]) if m else 0.0

    # --- availability signals (min over the window; missing = assume up)
    for key, name in (("dep_min", "dependency_up"), ("up_min", "up")):
        m = _metric(evidence, name)
        if m:
            recent = _values(m)[-6:]  # last ~3 minutes
            f[key] = min(recent) if recent else 1.0
        else:
            missing += 1
            f[key] = 1.0

    # --- logs
    logs = evidence.get("logs") or {}
    if "error" in logs or not logs:
        missing += 1
        f.update(log_error_lines=0.0, log_dependency_frac=0.0, log_timeout_frac=0.0,
                 log_app_error_frac=0.0)
    else:
        total = dep = tmo = app = 0
        for item in logs.get("top_messages") or []:
            n = int(item.get("count", 1))
            msg = str(item.get("msg", ""))
            total += n
            dep += n * bool(_DEP.search(msg))
            tmo += n * bool(_TIMEOUT.search(msg))
            app += n * bool(_APP.search(msg))
        events = logs.get("events") or {}
        dep += int(events.get("dependency_error", 0))
        total = max(total, 1)
        f["log_error_lines"] = math.log1p(float(logs.get("error_lines", 0)))
        f["log_dependency_frac"] = min(dep / total, 1.0)
        f["log_timeout_frac"] = min(tmo / total, 1.0)
        f["log_app_error_frac"] = min(app / total, 1.0)

    # --- deployments relative to when the evidence was collected
    collected = _parse_ts(evidence.get("collected_at"))
    since, rollback = DEPLOY_WINDOW_MIN, 0.0
    for d in evidence.get("deployments") or []:
        ts = _parse_ts(d.get("ts"))
        if not ts or not collected:
            continue
        age = (collected - ts).total_seconds() / 60.0
        if age < 0:
            continue
        if d.get("event") == "deploy" and d.get("status") == "success":
            since = min(since, age)
        if d.get("event") == "rollback" and age <= RECENT_DEPLOY_MIN:
            rollback = 1.0
    f["mins_since_deploy"] = since
    f["recent_deploy"] = float(since <= RECENT_DEPLOY_MIN)
    f["recent_rollback"] = rollback

    # --- alert categories (ground-truth/experiment alerts are never inputs)
    cats = {str(a.get("category")) for a in (alerts or [])
            if (a.get("labels") or {}).get("ground_truth") != "true"
            and a.get("category") != "experiment"}
    for cat in ("errors", "latency", "saturation", "dependency", "availability"):
        f[f"alert_{cat}"] = float(cat in cats)

    f["missing_signals"] = float(missing)
    return {name: float(f[name]) for name in FEATURE_NAMES}


def to_vector(features: dict[str, float]) -> list[float]:
    return [features[name] for name in FEATURE_NAMES]
