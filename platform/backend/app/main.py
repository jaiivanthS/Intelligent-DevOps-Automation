"""Platform API: one backend for the DevOps website.

Aggregates Jenkins, Prometheus, Loki, Alertmanager, the demo-app and the
app host's release state, and receives events from Jenkins and alerts from
Alertmanager (incident collector).

Run locally: uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from . import recovery
from .clients import (
    Alertmanager,
    App,
    Jenkins,
    Loki,
    Prometheus,
    ReleaseState,
    UpstreamError,
)
from .config import Settings, get_settings
from .db import Database, dumps, utcnow
from .incidents import (
    EVIDENCE_QUERIES,
    collect_evidence,
    ingest_alertmanager,
    run_rca,
    set_status,
)

try:  # RCA is optional: the platform runs without the rca_engine package.
    from rca_engine import RCAEngine
except ImportError:  # pragma: no cover
    RCAEngine = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("platform")

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# One static, fully parameterised query; ? = 'all' | 'active' | a concrete status.
INCIDENT_LIST_SQL = """
SELECT id, service, title, severity, category, status, opened_at, updated_at, resolved_at,
       rca IS NOT NULL AS has_rca,
       (SELECT COUNT(*) FROM alerts a WHERE a.incident_id = incidents.id) AS alert_count
FROM incidents
WHERE ? = 'all' OR (? = 'active' AND status != 'resolved') OR status = ?
ORDER BY id DESC LIMIT ?
"""


class Context:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.jenkins = Jenkins(http, settings)
        self.prom = Prometheus(http, settings.prometheus_url)
        self.loki = Loki(http, settings.loki_url)
        self.am = Alertmanager(http, settings.alertmanager_url)
        self.app = App(http, settings.app_url)
        self.state = ReleaseState(settings.app_state_dir)
        self.rca = RCAEngine.load(settings.rca_model_path) if RCAEngine else None

    async def evidence(self, incident_id: int) -> dict[str, Any]:
        return await collect_evidence(self.db, incident_id, self.prom, self.loki, self.state,
                                      self.settings.service_name, self.rca)


async def attempt(coro: Awaitable[Any]) -> dict[str, Any]:
    """Run an upstream call; never raise. The UI renders `error` as 'unavailable'."""
    try:
        return {"ok": True, "data": await coro}
    except UpstreamError as exc:
        return {"ok": False, "error": str(exc)}


class JenkinsEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    event: str = Field(min_length=1, max_length=50)
    status: str = Field(min_length=1, max_length=50)
    build: str | None = None
    image_tag: str | None = None
    environment: str | None = None


class StatusChange(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


Name = Annotated[str, Field(min_length=2, max_length=80, pattern=r"^[\w .@'-]+$")]


class RecoveryRequest(BaseModel):
    action: Literal["rollback", "restart"]
    reason: str = Field(min_length=3, max_length=2000)
    requested_by: Name
    target_image: str | None = Field(default=None, max_length=300)
    incident_id: int | None = None


class RecoveryDecision(BaseModel):
    by: Name
    note: str | None = Field(default=None, max_length=2000)
    approval_token: str | None = Field(default=None, max_length=200)


class RecoveryResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["succeeded", "failed"]
    detail: str | None = Field(default=None, max_length=4000)
    build: str | None = None
    smoke_test: dict[str, Any] | None = None


def create_app(settings: Settings | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=settings.upstream_timeout,
                                     transport=transport) as http:
            app.state.ctx = Context(settings, http)
            yield
            app.state.ctx.db.close()

    app = FastAPI(title="DevOps Platform API", version="1.0.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["*"], allow_headers=["*"])

    def ctx(request: Request) -> Context:
        return request.app.state.ctx

    def require_ingest_token(x_platform_token: str | None = Header(default=None)) -> None:
        if settings.ingest_token and not hmac.compare_digest(
                x_platform_token or "", settings.ingest_token):
            raise HTTPException(401, "invalid ingest token")

    # ------------------------------------------------------------------- health
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def config(c: Context = Depends(ctx)) -> dict[str, Any]:
        """Which integrations are configured (for the UI's status badges)."""
        return {
            "service": settings.service_name,
            "jenkins": c.jenkins.configured, "prometheus": c.prom.configured,
            "loki": c.loki.configured, "alertmanager": c.am.configured,
            "app": c.app.configured, "release_state": c.state.configured,
            "jenkins_url": settings.jenkins_url or None,
            "rca": c.rca.name if c.rca else None,
        }

    # ------------------------------------------------------------------ ingest
    @app.post("/api/events/jenkins", status_code=201, dependencies=[Depends(require_ingest_token)])
    def jenkins_event(evt: JenkinsEvent, c: Context = Depends(ctx)) -> dict[str, Any]:
        with c.db.tx() as conn:
            cur = conn.execute(
                "INSERT INTO events (ts, source, event, status, build, image_tag, environment, "
                "payload) VALUES (?, 'jenkins', ?, ?, ?, ?, ?, ?)",
                (utcnow(), evt.event, evt.status, evt.build, evt.image_tag, evt.environment,
                 dumps(evt.model_dump())))
        return {"id": cur.lastrowid}

    @app.post("/api/alerts/alertmanager", dependencies=[Depends(require_ingest_token)])
    async def alertmanager_webhook(payload: dict[str, Any], background: BackgroundTasks,
                                   c: Context = Depends(ctx)) -> dict[str, Any]:
        if not isinstance(payload.get("alerts"), list):
            raise HTTPException(422, "payload.alerts must be a list")
        opened = ingest_alertmanager(c.db, payload, settings.service_name)
        for incident_id in opened:
            log.info("incident %s opened", incident_id)
            background.add_task(c.evidence, incident_id)  # evidence, then RCA
        return {"received": len(payload["alerts"]), "opened_incidents": opened}

    # --------------------------------------------------------------- dashboard
    @app.get("/api/dashboard")
    async def dashboard(c: Context = Depends(ctx)) -> dict[str, Any]:
        q = EVIDENCE_QUERIES
        app_info, builds, rps, err, p95, alerts = await asyncio.gather(
            attempt(c.app.info()), attempt(c.jenkins.builds(5)),
            attempt(c.prom.scalar(q["request_rate"])), attempt(c.prom.scalar(q["error_ratio"])),
            attempt(c.prom.scalar(q["latency_p95"])), attempt(c.am.active()))
        open_incidents = c.db.query(
            "SELECT id, title, severity, category, status, opened_at FROM incidents "
            "WHERE status != 'resolved' ORDER BY id DESC LIMIT 5")
        last_pipeline = c.db.one(
            "SELECT * FROM events WHERE event = 'pipeline' ORDER BY id DESC LIMIT 1")
        return {
            "service": {"name": settings.service_name, "info": app_info,
                        "request_rate": rps, "error_ratio": err, "latency_p95": p95},
            "pipeline": {"builds": builds, "last_event": last_pipeline},
            "release": c.state.current(),
            "incidents": {"open": open_incidents,
                          "open_count": c.db.one("SELECT COUNT(*) AS n FROM incidents "
                                                 "WHERE status != 'resolved'")["n"]},
            "alerts": alerts,
            "events": c.db.query("SELECT * FROM events ORDER BY id DESC LIMIT 10"),
        }

    # ---------------------------------------------------------------- pipeline
    @app.get("/api/pipeline/builds")
    async def builds(limit: int = Query(20, ge=1, le=100),
                     c: Context = Depends(ctx)) -> dict[str, Any]:
        result = await attempt(c.jenkins.builds(limit))
        # Fallback when Jenkins' API is unreachable: what Jenkins told us via events.
        result["events"] = c.db.query(
            "SELECT * FROM events WHERE source = 'jenkins' ORDER BY id DESC LIMIT ?", (limit * 8,))
        return result

    @app.get("/api/pipeline/builds/{number}")
    async def build_detail(number: int, c: Context = Depends(ctx)) -> dict[str, Any]:
        stages, tests = await asyncio.gather(attempt(c.jenkins.stages(number)),
                                             attempt(c.jenkins.tests(number)))
        events = c.db.query("SELECT * FROM events WHERE build = ? ORDER BY id", (str(number),))
        return {"number": number, "stages": stages, "tests": tests, "events": events}

    @app.get("/api/pipeline/builds/{number}/log")
    async def build_log(number: int, lines: int = Query(300, ge=10, le=5000),
                        c: Context = Depends(ctx)) -> dict[str, Any]:
        return await attempt(c.jenkins.log_tail(number, lines))

    # ------------------------------------------------------------- deployments
    @app.get("/api/deployments")
    async def deployments(c: Context = Depends(ctx)) -> dict[str, Any]:
        return {
            "release": c.state.current(),
            "running": await attempt(c.app.info()),
            "history": c.state.history(50),
            "events": c.db.query(
                "SELECT * FROM events WHERE event IN ('approval', 'deploy', 'smoke_test', "
                "'rollback', 'release') ORDER BY id DESC LIMIT 50"),
        }

    # -------------------------------------------------------------- monitoring
    @app.get("/api/monitoring")
    async def monitoring(minutes: int = Query(60, ge=5, le=1440),
                         c: Context = Depends(ctx)) -> dict[str, Any]:
        step = max(15, minutes * 60 // 240)
        names = ["request_rate", "error_ratio", "latency_p95", "memory_rss_bytes",
                 "cpu_cores", "in_flight", "dependency_up"]
        results = await asyncio.gather(
            *(attempt(c.prom.series(EVIDENCE_QUERIES[n], minutes, step)) for n in names),
            attempt(c.prom.targets()), attempt(c.am.active()))
        series = {}
        for name, res in zip(names, results[: len(names)], strict=True):
            if res["ok"]:
                pts = res["data"][0]["points"] if res["data"] else []
                series[name] = {"ok": True, "points": pts}
            else:
                series[name] = res
        return {"minutes": minutes, "step": step, "series": series,
                "targets": results[-2], "alerts": results[-1]}

    # -------------------------------------------------------------------- logs
    @app.get("/api/logs")
    async def logs(level: str | None = None, search: str | None = Query(None, max_length=200),
                   event: str | None = Query(None, pattern=r"^[a-z_]{1,40}$"),
                   minutes: int = Query(60, ge=1, le=1440), limit: int = Query(200, ge=1, le=1000),
                   c: Context = Depends(ctx)) -> dict[str, Any]:
        selector = [f'service="{settings.service_name}"']
        if level:
            levels = [lv.upper() for lv in level.split(",")]
            if not set(levels) <= LOG_LEVELS:
                raise HTTPException(422, f"level must be among {sorted(LOG_LEVELS)}")
            selector.append(f'level=~"{"|".join(levels)}"')
        if event:
            selector.append(f'event="{event}"')
        logql = "{" + ", ".join(selector) + "}"
        if search:
            escaped = search.replace("\\", "\\\\").replace('"', '\\"')
            logql += f' |= "{escaped}"'
        result = await attempt(c.loki.query(logql, minutes, limit))
        result["query"] = logql
        return result

    @app.get("/api/alerts/active")
    async def active_alerts(c: Context = Depends(ctx)) -> dict[str, Any]:
        return await attempt(c.am.active())

    # --------------------------------------------------------------- incidents
    @app.get("/api/incidents")
    def incidents(status: Literal["open", "acknowledged", "resolved", "active"] | None = None,
                  limit: int = Query(50, ge=1, le=500),
                  c: Context = Depends(ctx)) -> list[dict[str, Any]]:
        mode = status or "all"
        return c.db.query(INCIDENT_LIST_SQL, (mode, mode, mode, limit))

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
        inc = c.db.one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        if inc is None:
            raise HTTPException(404, "incident not found")
        inc["alerts"] = c.db.query(
            "SELECT id, alertname, severity, category, status, starts_at, ends_at, labels, "
            "annotations FROM alerts WHERE incident_id = ? ORDER BY id", (incident_id,))
        return inc

    # Registered before the generic /{action} route, which would otherwise capture "rca".
    @app.post("/api/incidents/{incident_id}/rca")
    def rerun_rca(incident_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
        if c.rca is None:
            raise HTTPException(503, "RCA engine not installed")
        if c.db.one("SELECT id FROM incidents WHERE id = ?", (incident_id,)) is None:
            raise HTTPException(404, "incident not found")
        result = run_rca(c.db, incident_id, c.rca)
        if result is None:
            raise HTTPException(409, "no evidence collected for this incident yet")
        return result

    @app.post("/api/incidents/{incident_id}/{action}")
    def incident_action(incident_id: int, action: Literal["acknowledge", "resolve", "reopen"],
                        body: StatusChange | None = None,
                        c: Context = Depends(ctx)) -> dict[str, Any]:
        status = {"acknowledge": "acknowledged", "resolve": "resolved", "reopen": "open"}[action]
        if not set_status(c.db, incident_id, status, body.note if body else None):
            raise HTTPException(404, "incident not found")
        return c.db.one("SELECT id, status, updated_at FROM incidents WHERE id = ?",
                        (incident_id,))

    @app.post("/api/incidents/{incident_id}/evidence/refresh")
    async def refresh_evidence(incident_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
        if c.db.one("SELECT id FROM incidents WHERE id = ?", (incident_id,)) is None:
            raise HTTPException(404, "incident not found")
        return await c.evidence(incident_id)

    @app.get("/api/events")
    def events(limit: int = Query(50, ge=1, le=500), c: Context = Depends(ctx)):
        return c.db.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    # ---------------------------------------------------------------- recovery
    def recovery_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except recovery.RecoveryError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.get("/api/recovery/options")
    def recovery_options(c: Context = Depends(ctx)) -> dict[str, Any]:
        result = recovery.options(c.db, c.state, c.jenkins.can_trigger)
        result["approval_token_required"] = bool(settings.recovery_approval_token)
        result["distinct_approver_required"] = settings.require_distinct_approver
        return result

    @app.get("/api/recovery/actions")
    def recovery_actions(limit: int = Query(50, ge=1, le=500),
                         c: Context = Depends(ctx)) -> list[dict[str, Any]]:
        recovery.expire_stale(c.db)
        return c.db.query("SELECT * FROM recovery_actions ORDER BY id DESC LIMIT ?", (limit,))

    @app.get("/api/recovery/actions/{action_id}")
    def recovery_action(action_id: int, c: Context = Depends(ctx)) -> dict[str, Any]:
        recovery.expire_stale(c.db)
        return recovery_call(recovery.get, c.db, action_id)

    @app.post("/api/recovery/actions", status_code=201)
    def request_recovery(req: RecoveryRequest, c: Context = Depends(ctx)) -> dict[str, Any]:
        return recovery_call(recovery.create, c.db, c.state, action=req.action,
                             target_image=req.target_image, incident_id=req.incident_id,
                             reason=req.reason, requested_by=req.requested_by)

    @app.post("/api/recovery/actions/{action_id}/reject")
    def reject_recovery(action_id: int, d: RecoveryDecision,
                        c: Context = Depends(ctx)) -> dict[str, Any]:
        return recovery_call(recovery.decide, c.db, action_id, approve=False, by=d.by,
                             note=d.note, require_distinct=False)

    @app.post("/api/recovery/actions/{action_id}/approve")
    async def approve_recovery(action_id: int, d: RecoveryDecision,
                               c: Context = Depends(ctx)) -> dict[str, Any]:
        if settings.recovery_approval_token and not hmac.compare_digest(
                d.approval_token or "", settings.recovery_approval_token):
            raise HTTPException(403, "invalid approval token")
        if not c.jenkins.can_trigger:
            raise HTTPException(503, "Jenkins is not configured; cannot execute recovery")
        row = recovery_call(recovery.decide, c.db, action_id, approve=True, by=d.by,
                            note=d.note, require_distinct=settings.require_distinct_approver)
        try:
            queue = await c.jenkins.trigger(settings.recovery_job, {
                "ACTION": row["action"], "TARGET_IMAGE": row["target_image"] or "",
                "REQUEST_ID": str(action_id), "INCIDENT_ID": str(row["incident_id"] or ""),
                "APPROVED_BY": d.by})
        except UpstreamError as exc:
            return recovery.mark_failed(c.db, action_id, f"could not start Jenkins job: {exc}")
        log.info("recovery %s approved by %s; Jenkins queued %s", action_id, d.by, queue)
        return recovery.mark_running(c.db, action_id, queue)

    @app.post("/api/recovery/actions/{action_id}/result",
              dependencies=[Depends(require_ingest_token)])
    async def recovery_result(action_id: int, res: RecoveryResult,
                              c: Context = Depends(ctx)) -> dict[str, Any]:
        """Called by the Jenkins recovery job when it finishes."""
        row = recovery_call(recovery.record_result, c.db, action_id,
                            succeeded=res.status == "succeeded", detail=res.detail,
                            build=res.build, health={"smoke_test": res.smoke_test})
        # Independent post-recovery check from the platform's side.
        check = await attempt(c.app.info())
        platform_check = {"checked_at": utcnow(), "reachable": check["ok"],
                          "ready": bool(check.get("data", {}).get("ready")),
                          "version": check.get("data", {}).get("version"),
                          "error": check.get("error")}
        if row["action"] == "rollback" and platform_check["version"]:
            platform_check["version_matches_target"] = (
                (row["target_image"] or "").endswith(":" + platform_check["version"]))
        return recovery.merge_health(c.db, action_id, {"platform_check": platform_check})

    return app


app = create_app()
