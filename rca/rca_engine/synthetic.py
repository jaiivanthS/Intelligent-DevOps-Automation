"""Synthetic incident generator.

Produces evidence snapshots in exactly the platform's format (30 min of 30 s
points, log summary, deployments, alerts) for each root cause, with realistic
noise and deliberate confounders:

* unrelated deployments (old, and sometimes recent) in non-deployment incidents
* missing metrics / Loki outages
* secondary symptoms (CPU saturation also raises latency, etc.)
* "hard" difficulty: weaker signals, more missing data, more confounders

It is a stand-in for labelled production data. Results on it are reported
separately from benchmark (RCAEval) and live-demo results.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from .causes import CAUSE_KEYS

STEP_S = 30
N_POINTS = 60  # 30 minutes


def _summarise(times: list[float], values: list[float]) -> dict[str, Any]:
    if not values:
        return {"now": None, "baseline": None, "max": None, "points": []}
    head = values[: max(1, len(values) // 3)]
    return {"now": values[-1], "baseline": statistics.median(head), "max": max(values),
            "points": [[int(t), float(v)] for t, v in zip(times, values, strict=True)]}


def _params(difficulty: str) -> dict[str, Any]:
    if difficulty == "hard":
        return dict(err=(0.02, 0.3), lat=(1.8, 10.0), cpu=(0.55, 0.95), mem=(0.01, 0.08),
                    dep_err=(0.1, 0.8), p_missing=0.12, p_logs_down=0.2, p_old_deploy=0.35,
                    p_recent_deploy=0.15, p_primary_missing=0.1, p_dep_log=0.5)
    return dict(err=(0.05, 0.6), lat=(3.0, 30.0), cpu=(0.75, 1.0), mem=(0.03, 0.15),
                dep_err=(0.3, 1.0), p_missing=0.04, p_logs_down=0.08, p_old_deploy=0.25,
                p_recent_deploy=0.06, p_primary_missing=0.0, p_dep_log=0.8)


def generate(cause: str | None, rng: np.random.Generator, difficulty: str = "standard",
             now: datetime | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (evidence, alerts). cause=None generates a normal (no-incident) window."""
    p = _params(difficulty)
    end = now or datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=int(rng.integers(0, 10**7)))
    t_end = end.timestamp()
    times = [t_end - (N_POINTS - 1 - i) * STEP_S for i in range(N_POINTS)]
    idx = np.arange(N_POINTS)

    # Onset: most faults 2-5 min before collection; leaks start earlier (slow burn).
    k = int(rng.integers(10, 31)) if cause == "memory_leak" else int(rng.integers(4, 11))
    onset = N_POINTS - k
    post = idx >= onset
    ramp = np.clip((idx - onset + 1) / 2.0, 0, 1)  # reaches full effect after ~1 min

    # --- normal behaviour
    rps0 = rng.uniform(0.5, 20)
    rps = rps0 * (1 + 0.1 * np.sin(idx / rng.uniform(4, 12)) + rng.normal(0, 0.05, N_POINTS))
    err = np.clip(rng.uniform(0, 0.01) + rng.normal(0, 0.002, N_POINTS), 0, 1)
    lat0 = rng.uniform(0.02, 0.2)
    lat = lat0 * (1 + np.abs(rng.normal(0, 0.1, N_POINTS)))
    mem0 = rng.uniform(60e6, 300e6)
    mem = mem0 * (1 + rng.normal(0, 0.005, N_POINTS))
    cpu = np.clip(rng.uniform(0.02, 0.3) * (1 + rng.normal(0, 0.2, N_POINTS)), 0, None)
    inflight = rng.poisson(rng.uniform(0.2, 3), N_POINTS).astype(float)
    dep = np.ones(N_POINTS)
    up = np.ones(N_POINTS)

    logs: dict[str, int] = {}   # msg -> count
    levels: dict[str, str] = {}
    events: dict[str, int] = {}

    def log(msg: str, count: int, level: str = "ERROR", event: str | None = None) -> None:
        if count <= 0:
            return
        logs[msg] = logs.get(msg, 0) + count
        levels[msg] = level
        if event:
            events[event] = events.get(event, 0) + count

    def u(lo_hi: tuple[float, float]) -> float:
        return float(rng.uniform(*lo_hi))

    reqs_post = float(rps0 * k * STEP_S)
    deployments: list[dict[str, Any]] = []
    truncate_after: int | None = None
    hidden: set[str] = set()

    if cause == "error_burst":
        e = u(p["err"])
        err = err + post * ramp * e
        lat = lat * (1 + post * rng.uniform(0, 0.3))
        log("Unhandled exception in request handler", int(reqs_post * e * rng.uniform(0.5, 1)),
            event="http_request")
        log("request", int(reqs_post * e), event="http_request")
    elif cause == "bad_deployment":
        mode = rng.choice(["errors", "latency", "both"], p=[0.6, 0.25, 0.15])
        if mode in ("errors", "both"):
            e = u(p["err"])
            err = err + post * ramp * e
            log("Internal server error: KeyError in serializer", int(reqs_post * e * 0.8))
            log("request", int(reqs_post * e), event="http_request")
        if mode in ("latency", "both"):
            lat = lat * (1 + post * ramp * (u(p["lat"]) - 1))
        if rng.random() < 0.2:
            mem = mem * (1 + post * 0.1)
        deployments.append({"age_min": max(0.5, k * STEP_S / 60 + rng.uniform(0, 4)),
                            "event": "deploy", "status": "success"})
    elif cause == "dependency_failure":
        e = u(p["dep_err"])
        dep = np.where(post, 0.0, dep)
        err = err + post * ramp * e
        lat = lat * (1 + post * rng.uniform(-0.3, 0.5))
        if rng.random() < p["p_dep_log"]:
            log("inventory-db connection refused (host=inventory-db port=5432)",
                int(reqs_post * e * rng.uniform(0.6, 1)), event="dependency_error")
        log("request", int(reqs_post * e), event="http_request")
        if rng.random() < 0.15:
            hidden.add("dependency_up")  # exporter didn't expose it
    elif cause == "latency_degradation":
        lat = lat * (1 + post * ramp * (u(p["lat"]) - 1))
        err = err + post * rng.uniform(0, 0.02)
        if rng.random() < 0.4:
            log("upstream request timed out after 5s", int(rng.integers(3, 40)), level="WARNING")
    elif cause == "cpu_saturation":
        target = u(p["cpu"])
        cpu = np.where(post, cpu + ramp * (target - cpu), cpu)
        lat = lat * (1 + post * ramp * rng.uniform(1, 7))
        inflight = inflight + post * ramp * rng.uniform(3, 20)
        err = err + post * rng.uniform(0, 0.03)
    elif cause == "memory_leak":
        rate = u(p["mem"])  # fraction of baseline per minute
        minutes = np.maximum(idx - onset, 0) * STEP_S / 60
        mem = mem + post * mem0 * rate * minutes
        lat = lat * (1 + post * minutes * 0.02)
        if rng.random() < 0.15:
            err = err + post * (minutes > minutes.max() * 0.7) * rng.uniform(0.02, 0.2)
            log("MemoryError while building response", int(rng.integers(2, 30)))
    elif cause == "service_down":
        up = np.where(post, 0.0, up)
        truncate_after = onset  # no samples once the target stops being scraped
        if rng.random() < 0.5:
            log("Worker process exited unexpectedly", int(rng.integers(1, 4)), level="CRITICAL")

    # --- confounders
    if cause not in (None, "bad_deployment"):
        if rng.random() < p["p_old_deploy"]:
            deployments.append({"age_min": rng.uniform(25, 110), "event": "deploy",
                                "status": "success"})
        if rng.random() < p["p_recent_deploy"]:
            deployments.append({"age_min": rng.uniform(1, 18), "event": "deploy",
                                "status": "success"})
    if rng.random() < 0.3:
        log("slow request", int(rng.integers(1, 6)), level="WARNING", event="http_request")

    series = {
        "request_rate": np.clip(rps, 0, None), "error_ratio": np.clip(err, 0, 1),
        "latency_p95": np.clip(lat, 0.001, None), "memory_rss_bytes": mem,
        "cpu_cores": np.clip(cpu, 0, None), "in_flight": np.clip(inflight, 0, None),
        "dependency_up": dep, "up": up,
    }
    primary = {"error_burst": "error_ratio", "latency_degradation": "latency_p95",
               "cpu_saturation": "cpu_cores", "memory_leak": "memory_rss_bytes"}.get(cause or "")

    metrics: dict[str, Any] = {}
    for name, values in series.items():
        if name in hidden or (name != "up" and rng.random() < p["p_missing"]) or (
                name == primary and rng.random() < p["p_primary_missing"]):
            metrics[name] = {"error": "prometheus: query failed"}
            continue
        vals = [float(v) for v in values]
        ts = times
        if truncate_after is not None and name != "up":
            vals, ts = vals[:truncate_after], times[:truncate_after]
        metrics[name] = _summarise(ts, vals)

    if rng.random() < p["p_logs_down"]:
        log_summary: dict[str, Any] = {"error": "loki: ConnectError"}
    else:
        top = sorted(logs.items(), key=lambda kv: kv[1], reverse=True)[:10]
        log_summary = {"error_lines": int(sum(logs.values())),
                       "top_messages": [{"msg": m, "level": levels[m], "count": c} for m, c in top],
                       "events": events}

    evidence = {
        "collected_at": end.isoformat(timespec="seconds"),
        "window_minutes": 30,
        "metrics": metrics,
        "logs": log_summary,
        "deployments": [{"ts": (end - timedelta(minutes=float(d["age_min"]))).isoformat(),
                         "event": d["event"], "status": d["status"],
                         "image_tag": f"{int(rng.integers(10, 99))}-{rng.integers(0, 16**8):08x}"}
                        for d in sorted(deployments, key=lambda d: d["age_min"])],
        "release": {"current_image": "repo/demo-app:new", "last_good_image": "repo/demo-app:old"},
    }
    return evidence, _alerts(series, cause, truncate_after is not None)


def _alerts(series: dict[str, np.ndarray], cause: str | None, down: bool) -> list[dict[str, Any]]:
    """Alerts the Prometheus rules would plausibly have fired (approximate thresholds)."""
    if cause is None:
        return []
    cats: set[str] = set()
    tail = slice(-4, None)
    if down:
        cats.add("availability")
    else:
        if series["error_ratio"][tail].mean() > 0.05:
            cats.add("errors")
        if series["latency_p95"][tail].mean() > 0.5:
            cats.add("latency")
        if series["cpu_cores"][tail].mean() > 0.8 or series["memory_rss_bytes"][-1] > 400e6:
            cats.add("saturation")
        if series["dependency_up"][tail].min() < 1:
            cats.add("dependency")
    if not cats:  # the incident exists because *something* alerted
        cats.add({"memory_leak": "saturation", "latency_degradation": "latency",
                  "cpu_saturation": "saturation"}.get(cause, "errors"))
    return [{"alertname": c, "category": c, "labels": {}} for c in sorted(cats)]


def dataset(n_per_class: int, seed: int, difficulty: str | dict[str, float] = "standard",
            ) -> tuple[list[dict], list[list[dict]], list[str]]:
    """Balanced dataset. `difficulty` may be a mix, e.g. {"standard": 0.7, "hard": 0.3}."""
    rng = np.random.default_rng(seed)
    mix = {difficulty: 1.0} if isinstance(difficulty, str) else difficulty
    names, weights = list(mix), np.array(list(mix.values()), dtype=float)
    evidences, alerts, labels = [], [], []
    for cause in CAUSE_KEYS:
        for _ in range(n_per_class):
            diff = str(rng.choice(names, p=weights / weights.sum()))
            ev, al = generate(cause, rng, diff)
            evidences.append(ev)
            alerts.append(al)
            labels.append(cause)
    return evidences, alerts, labels


def normal_windows(n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [generate(None, rng)[0] for _ in range(n)]
