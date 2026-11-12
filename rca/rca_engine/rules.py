"""Rule-based RCA baseline.

Transparent, hand-written scoring over the same features the ML model uses.
It is the reference the ML models must beat, and the fallback when no
trained model is available.
"""

from __future__ import annotations

from .causes import CAUSE_KEYS


def score(f: dict[str, float]) -> dict[str, float]:
    s = dict.fromkeys(CAUSE_KEYS, 0.0)
    errors_up = f["err_delta"] > 0.02 or f["err_now"] > 0.05
    slow = f["lat_log_ratio"] > 1.0  # p95 more than ~2.7x baseline
    dep_logs = f["log_dependency_frac"] > 0.3

    if f["up_min"] < 1:
        s["service_down"] += 3.0
    if f["dep_min"] < 1:
        s["dependency_failure"] += 3.0
    if dep_logs:
        # "connection refused" logs are strong evidence even if dependency_up isn't exported
        s["dependency_failure"] += 2.0
    if f["recent_deploy"] and (errors_up or slow):
        s["bad_deployment"] += 2.5
    if f["mem_growth_per_min"] > 0.03 or f["mem_log_ratio"] > 0.4:
        s["memory_leak"] += 2.5
    if f["cpu_now"] > 0.7 or f["cpu_delta"] > 0.5:
        s["cpu_saturation"] += 2.5
    if slow and f["cpu_now"] < 0.5 and not errors_up:
        s["latency_degradation"] += 2.0
    if slow and f["log_timeout_frac"] > 0.3:
        s["latency_degradation"] += 1.0
    if errors_up and not f["recent_deploy"] and not dep_logs:
        s["error_burst"] += 1.5
    if f["log_app_error_frac"] > 0.3 and not f["recent_deploy"]:
        s["error_burst"] += 0.5
    # weak priors so there is always a ranking
    s["error_burst"] += 0.1 * errors_up
    s["latency_degradation"] += 0.1 * slow
    return s


def rank(f: dict[str, float]) -> list[tuple[str, float]]:
    """Causes sorted by score, scores normalised to sum to 1."""
    s = score(f)
    total = sum(s.values())
    if total <= 0:
        n = len(s)
        return [(k, 1.0 / n) for k in s]
    return sorted(((k, v / total) for k, v in s.items()), key=lambda kv: kv[1], reverse=True)


def predict(f: dict[str, float]) -> str:
    return rank(f)[0][0]
