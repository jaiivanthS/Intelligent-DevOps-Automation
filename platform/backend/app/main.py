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
from typing import Any, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

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
from .incidents import EVIDENCE_QUERIES, collect_evidence, ingest_alertmanager, set_status

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
            background.add_task(collect_evidence, c.db, incident_id, c.prom, c.loki, c.state,
                                settings.service_name)
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
        return await collect_evidence(c.db, incident_id, c.prom, c.loki, c.state,
                                      settings.service_name)

    @app.get("/api/events")
    def events(limit: int = Query(50, ge=1, le=500), c: Context = Depends(ctx)):
        return c.db.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    return app


app = create_app()
