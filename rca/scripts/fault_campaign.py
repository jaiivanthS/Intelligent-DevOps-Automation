"""Live fault-injection campaign for evaluating detection and RCA on real telemetry.

For each trial: inject one fault into demo-app through its chaos API, wait for the
platform to open an incident and run RCA, stop the fault, wait for the incident to
resolve, then cool down so the next trial starts from a healthy baseline (and is not
merged into the previous incident by the platform's 5-minute reopen rule).

Fault strengths are drawn at random per trial; a fault that never raises an alert is
recorded as a missed detection, not dropped.

    python rca/scripts/fault_campaign.py --app http://localhost:8088 \
        --platform http://localhost:8081 --prometheus http://localhost:9090 \
        --token-file chaos.token --per-mode 5 --out rca/data/live_campaign.jsonl

Stdlib only. Results are appended one JSON line per trial, so an interrupted run keeps
what it has (use --skip to resume). Then:
    python -m rca_engine.live export --api http://localhost:8081 --out rca/data/live.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

MODES = ["dependency_failure", "error_rate", "latency_ms", "cpu_burn_ms", "memory_leak_mb"]
DETECT_TIMEOUT_S = 7 * 60    # no incident with RCA by then -> missed detection
RESOLVE_TIMEOUT_S = 12 * 60
COOLDOWN_S = 6 * 60          # > platform REOPEN_WINDOW_MIN (5) after the last resolution
POLL_S = 5


def fault_for(mode: str, rng: random.Random) -> dict:
    if mode == "dependency_failure":
        return {"dependency_failure": True}
    if mode == "error_rate":
        return {"error_rate": round(rng.uniform(0.10, 0.50), 2)}
    if mode == "latency_ms":
        return {"latency_ms": rng.randrange(700, 2001, 50)}
    if mode == "cpu_burn_ms":
        return {"cpu_burn_ms": rng.randrange(350, 601, 25)}
    if mode == "memory_leak_mb":
        return {"memory_leak_mb": rng.choice([1, 2])}
    raise ValueError(mode)


class Api:
    def __init__(self, app: str, platform: str, prometheus: str, token: str) -> None:
        for url in (app, platform, prometheus):
            if not url.startswith(("http://", "https://")):
                raise ValueError("URLs must be http(s)")
        self.app, self.platform, self.prom, self.token = (
            app.rstrip("/"), platform.rstrip("/"), prometheus.rstrip("/"), token)

    def _call(self, url: str, method: str = "GET", body: dict | None = None,
              headers: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        # Scheme restricted to http(s) in __init__.
        req = urllib.request.Request(url, data=data, method=method, headers={  # noqa: S310
            "Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310  # nosec B310
            raw = r.read()
            return json.loads(raw) if raw else None

    def chaos(self, fault: dict | None) -> dict:
        h = {"X-Chaos-Token": self.token}
        if fault is None:
            return self._call(f"{self.app}/chaos", "DELETE", headers=h)
        return self._call(f"{self.app}/chaos", "POST", fault, h)

    def alerts(self) -> list[dict]:
        """Non-ground-truth demo-app alerts as (name, state)."""
        data = self._call(f"{self.prom}/api/v1/alerts")["data"]["alerts"]
        return [{"name": a["labels"]["alertname"], "state": a["state"]} for a in data
                if a["labels"].get("ground_truth") != "true"
                and a["labels"].get("service", "demo-app") == "demo-app"]

    def incidents(self) -> list[dict]:
        return self._call(f"{self.platform}/api/incidents?limit=50")

    def incident(self, iid: int) -> dict:
        return self._call(f"{self.platform}/api/incidents/{iid}")

    def healthy(self) -> bool:
        try:
            self._call(f"{self.app}/ready")
            return True
        except Exception:  # noqa: BLE001 - any failure means not ready
            return False


def now() -> float:
    return time.time()


def iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds") if t else None


def wait_quiet(api: Api, log) -> None:
    """Healthy app, no demo-app alerts pending/firing, no active incident, and COOLDOWN_S
    since the most recent resolution."""
    while True:
        active = [i for i in api.incidents() if i["status"] in ("open", "acknowledged")]
        alerts = api.alerts()
        last_res = max((datetime.fromisoformat(i["resolved_at"]).timestamp()
                        for i in api.incidents() if i.get("resolved_at")), default=0)
        wait = COOLDOWN_S - (now() - last_res)
        if not active and not alerts and api.healthy() and wait <= 0:
            return
        log(f"  waiting for quiet: active={[i['id'] for i in active]} "
            f"alerts={[a['name'] + ':' + a['state'] for a in alerts]} cooldown={max(0, wait):.0f}s")
        time.sleep(min(60, max(POLL_S, wait)) if not active and not alerts else 20)


def run_trial(api: Api, mode: str, fault: dict, log) -> dict:
    known = {i["id"] for i in api.incidents()}
    rec: dict = {"mode": mode, "fault": fault}
    t0 = now()
    api.chaos(fault)
    rec["injected_at"] = iso(t0)
    first_alert = None
    incident_id = None
    while now() - t0 < DETECT_TIMEOUT_S:
        if first_alert is None and any(a["state"] == "firing" for a in api.alerts()):
            first_alert = now()
        new = [i for i in api.incidents() if i["id"] not in known]
        if new:
            incident_id = new[-1]["id"] if len(new) == 1 else min(i["id"] for i in new)
            inc = api.incident(incident_id)
            if inc.get("rca"):
                break
        time.sleep(POLL_S)
    t_detect = now()
    rec["first_alert_s"] = round(first_alert - t0) if first_alert else None
    if incident_id is None or not api.incident(incident_id).get("rca"):
        rec["detected"] = False
        log(f"  MISSED: no incident with RCA after {DETECT_TIMEOUT_S}s")
        api.chaos(None)
        rec["calm_at"] = iso(now())
        return rec

    inc = api.incident(incident_id)
    rca = inc["rca"]
    rec.update({
        "detected": True, "incident_id": incident_id,
        "incident_opened_at": inc["opened_at"],
        "incident_s": round(datetime.fromisoformat(inc["opened_at"]).timestamp() - t0),
        "rca_ready_s": round(t_detect - t0),
        "alerts": sorted({a["alertname"] for a in inc["alerts"]}),
        "ground_truth": sorted({g.get("mode") for g in inc.get("ground_truth") or []} - {None}),
        "rca_top": rca["top_cause"], "rca_confidence": rca["confidence"],
        "rca_ranking": [r["cause"] for r in rca["ranking"]],
        "rule_top": rca["rule_based"]["top_cause"],
        "suggested_action": rca["suggested_action"],
        "alternative_action": (rca.get("alternative_action") or {}).get("action"),
        "anomalous": (rca.get("anomaly") or {}).get("is_anomalous"),
    })
    log(f"  incident #{incident_id} at +{rec['incident_s']}s; RCA {rca['top_cause']} "
        f"({rca['confidence']:.2f}), rules {rec['rule_top']}")

    t_calm = now()
    api.chaos(None)
    rec["calm_at"] = iso(t_calm)
    while now() - t_calm < RESOLVE_TIMEOUT_S:
        inc = api.incident(incident_id)
        if inc["status"] == "resolved":
            rec["resolved_s_after_calm"] = round(
                datetime.fromisoformat(inc["resolved_at"]).timestamp() - t_calm)
            break
        time.sleep(POLL_S)
    else:
        rec["resolved_s_after_calm"] = None
        log("  incident did not resolve in time")
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", required=True)
    ap.add_argument("--platform", required=True)
    ap.add_argument("--prometheus", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--per-mode", type=int, default=5)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip", type=int, default=0, help="resume: skip the first N trials")
    ap.add_argument("--out", default="rca/data/live_campaign.jsonl")
    args = ap.parse_args()

    api = Api(args.app, args.platform, args.prometheus,
              Path(args.token_file).read_text(encoding="utf-8").strip())
    rng = random.Random(args.seed)  # nosec B311 - reproducible experiment, not security
    modes = args.modes.split(",")
    # Round-robin order, so a partial run is still balanced across fault types.
    plan = [(m, fault_for(m, rng)) for _ in range(args.per_mode) for m in modes]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(f"{datetime.now(UTC):%H:%M:%SZ} {msg}", flush=True)

    log(f"campaign: {len(plan)} trials ({args.per_mode} x {modes}), skipping {args.skip}")
    for n, (mode, fault) in enumerate(plan, 1):
        if n <= args.skip:
            continue
        wait_quiet(api, log)
        log(f"trial {n}/{len(plan)}: {mode} {fault}")
        try:
            rec = run_trial(api, mode, fault, log)
        except Exception as exc:  # keep going; record the failure
            api.chaos(None)
            rec = {"mode": mode, "fault": fault, "error": repr(exc)}
            log(f"  ERROR {exc!r}")
        rec["trial"] = n
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    wait_quiet(api, log)
    log("campaign finished")


if __name__ == "__main__":
    main()
