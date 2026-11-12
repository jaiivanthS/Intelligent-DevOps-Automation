"""RCA engine: evidence in, explainable ranked causes out.

    engine = RCAEngine.load("model.joblib")    # falls back to rules if the file is missing
    result = engine.analyze(evidence, alerts)

Result (stored as incidents.rca by the platform):
    top_cause, top_cause_title, confidence, ranking[{cause, title, score}],
    evidence[str], suggested_checks[str], suggested_action, model,
    rule_based{top_cause, ranking}, anomaly{score, is_anomalous, top_deviations}
"""

from __future__ import annotations

import logging
import os
from typing import Any

from . import rules
from .causes import CAUSES
from .features import extract
from .model import RCAModel

log = logging.getLogger("rca")


class RCAEngine:
    def __init__(self, model: RCAModel | None = None) -> None:
        self.model = model

    @classmethod
    def load(cls, path: str | None) -> RCAEngine:
        if path and os.path.exists(path):
            try:
                return cls(RCAModel.load(path))
            except Exception:  # corrupt/incompatible model must not take the platform down
                log.exception("could not load RCA model from %s; using rule-based baseline", path)
        else:
            log.warning("RCA model %s not found; using rule-based baseline", path)
        return cls(None)

    @property
    def name(self) -> str:
        if self.model is None:
            return "rule-based baseline"
        return f"{self.model.kind} + isolation forest"

    def analyze(self, evidence: dict[str, Any], alerts: list[dict[str, Any]] | None = None
                ) -> dict[str, Any]:
        f = extract(evidence, alerts)
        rule_rank = rules.rank(f)
        ranking = self.model.rank(f) if self.model else rule_rank
        top, confidence = ranking[0]
        cause = CAUSES[top]

        action = cause.action
        release = evidence.get("release") or {}
        if action == "rollback" and not release.get("last_good_image"):
            action = "none"  # nothing known-good to roll back to

        return {
            "top_cause": top,
            "top_cause_title": cause.title,
            "description": cause.description,
            "confidence": round(confidence, 3),
            "ranking": [{"cause": c, "title": CAUSES[c].title, "score": round(s, 3)}
                        for c, s in ranking[:4]],
            "evidence": explain(f, evidence, top),
            "suggested_checks": list(cause.checks),
            "suggested_action": action,
            "model": self.name,
            "rule_based": {"top_cause": rule_rank[0][0],
                           "ranking": [{"cause": c, "score": round(s, 3)} for c, s in rule_rank[:3]]},
            "anomaly": self.model.anomaly(f) if self.model else None,
            "features": {k: round(v, 4) for k, v in f.items()},
        }


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _metric_pair(evidence: dict, name: str) -> tuple[float | None, float | None]:
    m = (evidence.get("metrics") or {}).get(name) or {}
    return m.get("baseline"), m.get("now")


def explain(f: dict[str, float], evidence: dict[str, Any], top: str) -> list[str]:
    """Human-readable facts supporting (or qualifying) the diagnosis, most relevant first."""
    facts: list[tuple[int, str]] = []  # (priority, text); lower = more relevant

    def add(relevant_to: set[str], text: str) -> None:
        facts.append((0 if top in relevant_to else 1, text))

    base, now = _metric_pair(evidence, "error_ratio")
    if f["err_delta"] > 0.02 or f["err_now"] > 0.05:
        add({"error_burst", "bad_deployment", "dependency_failure"},
            f"5xx error ratio rose from {_pct(base or 0)} to {_pct(now or f['err_now'])}.")
    if f["lat_log_ratio"] > 1.0:
        b, n = _metric_pair(evidence, "latency_p95")
        add({"latency_degradation", "cpu_saturation", "bad_deployment"},
            f"p95 latency increased {pow(2.718, f['lat_log_ratio']):.1f}x "
            f"(from {1000 * (b or 0):.0f} ms to {1000 * (n or f['lat_now']):.0f} ms).")
    if f["dep_min"] < 1:
        add({"dependency_failure"}, "Dependency health check failed (dependency_up = 0).")
    if f["log_dependency_frac"] > 0.3:
        add({"dependency_failure"},
            f"{_pct(f['log_dependency_frac'])} of error logs mention connection/dependency failures.")
    if f["log_timeout_frac"] > 0.3:
        add({"latency_degradation"}, f"{_pct(f['log_timeout_frac'])} of error logs mention timeouts.")
    if f["log_app_error_frac"] > 0.3:
        add({"error_burst", "bad_deployment"},
            f"{_pct(f['log_app_error_frac'])} of error logs are application failures.")
    if f["cpu_now"] > 0.5:
        add({"cpu_saturation"}, f"Process CPU at {f['cpu_now']:.2f} cores "
                                f"(+{f['cpu_delta']:.2f} vs baseline).")
    if f["mem_growth_per_min"] > 0.01 or f["mem_log_ratio"] > 0.2:
        add({"memory_leak"}, f"Memory grew {_pct(pow(2.718, f['mem_log_ratio']) - 1)} over the window "
                             f"({_pct(f['mem_growth_per_min'])} of baseline per minute).")
    if f["up_min"] < 1:
        add({"service_down"}, "Prometheus could not scrape the service (up = 0).")
    if f["recent_deploy"]:
        tag = next((d.get("image_tag") for d in evidence.get("deployments") or []
                    if d.get("event") == "deploy" and d.get("status") == "success"), None)
        add({"bad_deployment"}, f"A deployment{f' ({tag})' if tag else ''} finished "
                                f"{f['mins_since_deploy']:.0f} min before the evidence was collected.")
    elif top == "bad_deployment":
        add({"bad_deployment"}, "No deployment in the last 20 minutes; treat this diagnosis with care.")
    if f["missing_signals"] >= 3:
        facts.append((2, f"{int(f['missing_signals'])} telemetry sources were unavailable; "
                         "confidence is reduced."))
    facts.sort(key=lambda p: p[0])
    return [text for _, text in facts][:6]
