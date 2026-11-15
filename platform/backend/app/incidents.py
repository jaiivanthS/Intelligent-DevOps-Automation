"""Incident collector: turns Alertmanager notifications into incidents and
attaches an evidence snapshot (metrics, logs, recent deployments) when an
incident opens. The RCA engine (step 7) reads that evidence.

Correlation rule: a firing alert joins the open incident of the same service; if
that service's last incident resolved less than REOPEN_WINDOW_MIN ago, it reopens
it; otherwise it opens a new one. An incident resolves when all its alerts resolve.
Alerts labelled ground_truth="true" (deliberate fault injection) are kept
separately and never used as evidence, only for evaluating RCA.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from .clients import Loki, Prometheus, ReleaseState, UpstreamError
from .db import Database, dumps, utcnow

log = logging.getLogger("platform.incidents")

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
OPEN_STATES = ("open", "acknowledged")

_API = 'job="demo-app", route!~"/health|/ready|/metrics"'
EVIDENCE_QUERIES: dict[str, str] = {
    "request_rate": f"sum(rate(http_requests_total{{{_API}}}[2m]))",
    "error_ratio": 'sum(rate(http_requests_total{job="demo-app", status=~"5.."}[2m]))'
                   ' / clamp_min(sum(rate(http_requests_total{job="demo-app"}[2m])), 1e-9)',
    "latency_p95": "histogram_quantile(0.95, sum by (le) "
                   f"(rate(http_request_duration_seconds_bucket{{{_API}}}[2m])))",
    "memory_rss_bytes": 'max(process_resident_memory_bytes{job="demo-app"})',
    "cpu_cores": 'max(rate(process_cpu_seconds_total{job="demo-app"}[2m]))',
    "in_flight": 'max(http_requests_in_progress{job="demo-app"})',
    "dependency_up": 'min(dependency_up{job="demo-app"})',
    "up": 'min(up{job="demo-app"})',
}
EVIDENCE_WINDOW_MIN = 30
EVIDENCE_STEP_S = 30


def fingerprint(labels: dict[str, str]) -> str:
    raw = json.dumps(labels, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _open_incident(c, service: str):
    return c.execute(
        "SELECT * FROM incidents WHERE service = ? AND status IN (?, ?) ORDER BY id DESC LIMIT 1",
        (service, *OPEN_STATES),
    ).fetchone()


# An alert that fires this soon after an incident resolved is treated as the same problem
# (typically a 5-minute rate window still above threshold after the fault was fixed) and
# reopens that incident instead of opening a new one.
REOPEN_WINDOW_MIN = 5


def _reopen_recent(c, service: str, alertname: str, now: str):
    since = (datetime.fromisoformat(now) - timedelta(minutes=REOPEN_WINDOW_MIN)).isoformat(
        timespec="seconds")
    inc = c.execute(
        "SELECT * FROM incidents WHERE service = ? AND status = 'resolved' AND resolved_at > ? "
        "ORDER BY resolved_at DESC LIMIT 1", (service, since)).fetchone()
    if inc is None:
        return None
    notes = json.loads(inc["notes"] or "[]")
    notes.append({"ts": now, "status": "open",
                  "note": f"Reopened: {alertname} fired within {REOPEN_WINDOW_MIN} min of "
                          "resolution (treated as the same problem)."})
    c.execute("UPDATE incidents SET status = 'open', resolved_at = NULL, updated_at = ?, "
              "notes = ? WHERE id = ?", (now, dumps(notes), inc["id"]))
    log.info("incident %s reopened by %s", inc["id"], alertname)
    return inc


def _firing_ground_truth(c, service: str) -> list[dict[str, Any]]:
    rows = c.execute(
        "SELECT labels, annotations, starts_at FROM alerts "
        "WHERE ground_truth = 1 AND status = 'firing' AND service = ?",
        (service,),
    ).fetchall()
    return [{"mode": json.loads(r["labels"]).get("mode"),
             "summary": json.loads(r["annotations"]).get("summary"),
             "starts_at": r["starts_at"]} for r in rows]


def ingest_alertmanager(db: Database, payload: dict[str, Any], default_service: str) -> list[int]:
    """Apply an Alertmanager webhook payload. Returns ids of newly opened incidents."""
    now = utcnow()
    opened: list[int] = []
    touched: set[int] = set()

    with db.tx() as c:
        for alert in payload.get("alerts", []):
            labels: dict[str, str] = alert.get("labels", {})
            annotations: dict[str, str] = alert.get("annotations", {})
            status = alert.get("status", "firing")
            fp = alert.get("fingerprint") or fingerprint(labels)
            service = labels.get("service", default_service)
            is_gt = labels.get("ground_truth") == "true"
            ends_at = alert.get("endsAt") if status == "resolved" else None
            row = c.execute("SELECT * FROM alerts WHERE fingerprint = ?", (fp,)).fetchone()

            if row is not None and (row["status"] == "firing" or status == "resolved"):
                # Update of an alert we already track (still firing, or now resolved).
                c.execute(
                    "UPDATE alerts SET status = ?, ends_at = ?, annotations = ?, updated_at = ? "
                    "WHERE id = ?",
                    (status, ends_at, dumps(annotations), now, row["id"]),
                )
                if row["incident_id"]:
                    touched.add(row["incident_id"])
                continue
            if status != "firing":
                continue  # resolution for an alert we never saw

            incident_id = None
            if is_gt:
                inc = _open_incident(c, service)
                if inc is not None:
                    gt = json.loads(inc["ground_truth"] or "[]")
                    gt.append({"mode": labels.get("mode"), "summary": annotations.get("summary"),
                               "starts_at": alert.get("startsAt")})
                    c.execute("UPDATE incidents SET ground_truth = ? WHERE id = ?",
                              (dumps(gt), inc["id"]))
            else:
                inc = _open_incident(c, service)
                if inc is None:
                    inc = _reopen_recent(c, service, labels.get("alertname", "alert"), now)
                    if inc is not None:
                        touched.add(inc["id"])
                if inc is None:
                    cur = c.execute(
                        "INSERT INTO incidents (service, title, severity, category, status, "
                        "opened_at, updated_at, ground_truth) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
                        (service,
                         annotations.get("summary") or labels.get("alertname", "alert"),
                         labels.get("severity", "warning"), labels.get("category", "unknown"),
                         now, now, dumps(_firing_ground_truth(c, service))),
                    )
                    incident_id = cur.lastrowid
                    opened.append(incident_id)
                else:
                    incident_id = inc["id"]
                touched.add(incident_id)

            values = (incident_id, labels.get("alertname", "alert"), service,
                      labels.get("severity", "warning"), labels.get("category", "unknown"),
                      int(is_gt), alert.get("startsAt"), dumps(labels), dumps(annotations), now)
            if row is None:
                c.execute(
                    "INSERT INTO alerts (incident_id, alertname, service, severity, category, "
                    "ground_truth, starts_at, labels, annotations, updated_at, status, fingerprint)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'firing', ?)", (*values, fp))
            else:  # a previously resolved alert fires again
                c.execute(
                    "UPDATE alerts SET incident_id = ?, alertname = ?, service = ?, severity = ?, "
                    "category = ?, ground_truth = ?, starts_at = ?, labels = ?, annotations = ?, "
                    "updated_at = ?, status = 'firing', ends_at = NULL WHERE fingerprint = ?",
                    (*values, fp))

        for incident_id in touched:
            _refresh(c, incident_id, now)
    return opened


def _refresh(c, incident_id: int, now: str) -> None:
    alerts = c.execute(
        "SELECT severity, status FROM alerts WHERE incident_id = ? AND ground_truth = 0",
        (incident_id,),
    ).fetchall()
    if not alerts:
        return
    severity = max((a["severity"] for a in alerts), key=lambda s: SEVERITY_RANK.get(s, 1))
    all_resolved = all(a["status"] == "resolved" for a in alerts)
    inc = c.execute("SELECT status FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if all_resolved and inc["status"] != "resolved":
        c.execute("UPDATE incidents SET severity = ?, status = 'resolved', resolved_at = ?, "
                  "updated_at = ? WHERE id = ?", (severity, now, now, incident_id))
    else:
        c.execute("UPDATE incidents SET severity = ?, updated_at = ? WHERE id = ?",
                  (severity, now, incident_id))


def set_status(db: Database, incident_id: int, status: str, note: str | None = None) -> bool:
    now = utcnow()
    with db.tx() as c:
        row = c.execute("SELECT notes FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if row is None:
            return False
        notes = json.loads(row["notes"] or "[]")
        if note:
            notes.append({"ts": now, "status": status, "note": note})
        c.execute(
            "UPDATE incidents SET status = ?, updated_at = ?, notes = ?, "
            "resolved_at = CASE WHEN ? = 'resolved' THEN ? ELSE resolved_at END WHERE id = ?",
            (status, now, json.dumps(notes), status, now, incident_id),
        )
    return True


# --------------------------------------------------------------------- evidence
# A fault is visible in the metrics a few minutes before its alert fires (rate windows +
# the rule's `for:` delay) and for a few minutes after it is fixed.
LEAD_S = 300
TAIL_S = 300


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _baseline_spans(db: Database, incident_id: int, service: str) -> tuple[float | None,
                                                                           list[list[float]]]:
    """(start of this incident's fault, [[start, end], ...] of other incidents' faults) so the
    baseline is computed only from healthy points."""
    row = db.one("SELECT opened_at FROM incidents WHERE id = ?", (incident_id,))
    this_start = _ts(row["opened_at"]) - LEAD_S if row else None
    since = (datetime.now(UTC) - timedelta(minutes=EVIDENCE_WINDOW_MIN + 10)).isoformat(
        timespec="seconds")
    spans = []
    for r in db.query("SELECT opened_at, resolved_at FROM incidents WHERE service = ? AND id != ? "
                      "AND (resolved_at IS NULL OR resolved_at >= ?)",
                      (service, incident_id, since)):
        end = _ts(r["resolved_at"]) + TAIL_S if r["resolved_at"] else float("inf")
        spans.append([_ts(r["opened_at"]) - LEAD_S, end])
    return this_start, spans


def _summarise(points: list[list[float]], this_start: float | None = None,
               exclude: list[list[float]] | None = None) -> dict[str, Any]:
    """now / baseline / max of a series. The baseline is the median of healthy points:
    before this incident's fault and outside other incidents. If there are too few of
    those, fall back to the first third of the window (flagged as baseline_clean=False)."""
    values = [v for _, v in points if v == v]  # drop NaN
    if not values:
        return {"now": None, "baseline": None, "max": None}
    healthy = [v for t, v in points if v == v
               and (this_start is None or t < this_start)
               and not any(a <= t <= b for a, b in exclude or [])]
    if len(healthy) >= 3:
        baseline, clean = statistics.median(healthy), True
    else:
        baseline, clean = statistics.median(values[: max(1, len(values) // 3)]), not exclude
    return {"now": values[-1], "baseline": baseline, "max": max(values), "baseline_clean": clean}


async def collect_evidence(db: Database, incident_id: int, prom: Prometheus, loki: Loki,
                           state: ReleaseState, service: str, engine: Any = None
                           ) -> dict[str, Any]:
    evidence: dict[str, Any] = {"collected_at": utcnow(), "window_minutes": EVIDENCE_WINDOW_MIN}

    this_start, exclude = _baseline_spans(db, incident_id, service)
    evidence["baseline_excluded"] = [[a, b if b != float("inf") else None] for a, b in exclude]
    metrics: dict[str, Any] = {}
    for name, expr in EVIDENCE_QUERIES.items():
        try:
            series = await prom.series(expr, EVIDENCE_WINDOW_MIN, EVIDENCE_STEP_S)
            points = series[0]["points"] if series else []
            metrics[name] = {**_summarise(points, this_start, exclude), "points": points}
        except UpstreamError as exc:
            metrics[name] = {"error": str(exc)}
    evidence["metrics"] = metrics

    try:
        lines = await loki.query(f'{{service="{service}", level=~"ERROR|WARNING"}}',
                                 minutes=15, limit=300)
        messages = Counter(
            ((entry["json"] or {}).get("msg") or entry["line"][:120],
             (entry["json"] or {}).get("level", "?"))
            for entry in lines
        )
        events = Counter((entry["json"] or {}).get("event") for entry in lines)
        evidence["logs"] = {
            "error_lines": len(lines),
            "top_messages": [{"msg": m, "level": lvl, "count": n}
                             for (m, lvl), n in messages.most_common(10)],
            "events": {k: v for k, v in events.items() if k},
            "samples": [entry["json"] or {"line": entry["line"]} for entry in lines[:20]],
        }
    except UpstreamError as exc:
        evidence["logs"] = {"error": str(exc)}

    since = (datetime.now(UTC) - timedelta(minutes=60)).isoformat(timespec="seconds")
    evidence["deployments"] = db.query(
        "SELECT ts, event, status, build, image_tag, environment FROM events "
        "WHERE ts >= ? AND event IN ('deploy', 'rollback', 'release', 'smoke_test') "
        "ORDER BY ts DESC LIMIT 20", (since,))
    evidence["release"] = state.current()
    evidence["release_history"] = state.history(10)

    with db.tx() as c:
        c.execute("UPDATE incidents SET evidence = ? WHERE id = ?", (dumps(evidence), incident_id))
    log.info("evidence collected for incident %s", incident_id)
    if engine is not None:
        run_rca(db, incident_id, engine)
    return evidence


def run_rca(db: Database, incident_id: int, engine: Any) -> dict[str, Any] | None:
    """Analyse the stored evidence with the RCA engine and save the result."""
    inc = db.one("SELECT evidence FROM incidents WHERE id = ?", (incident_id,))
    if inc is None or not inc["evidence"]:
        return None
    alerts = db.query("SELECT alertname, severity, category, labels FROM alerts "
                      "WHERE incident_id = ? AND ground_truth = 0", (incident_id,))
    try:
        result = engine.analyze(inc["evidence"], alerts)
    except Exception:  # RCA is advisory: a failure must never break incident handling
        log.exception("RCA failed for incident %s", incident_id)
        return None
    result["analyzed_at"] = utcnow()
    with db.tx() as c:
        c.execute("UPDATE incidents SET rca = ? WHERE id = ?", (dumps(result), incident_id))
    log.info("RCA for incident %s: %s (%.0f%%)", incident_id, result["top_cause"],
             100 * result["confidence"])
    return result
