"""Demo inventory service: the workload the DevOps platform builds, deploys,
monitors and recovers.

Run locally:  uvicorn app.main:app --port 8000 --no-access-log
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.routing import Match

from . import metrics
from .chaos import ChaosController
from .config import Settings, get_settings
from .inventory import DependencyUnavailable, InventoryStore, Item, ItemIn
from .logging_config import configure_logging

log = logging.getLogger("demo_app")
access_log = logging.getLogger("demo_app.access")

# Operational endpoints are never affected by injected failures, so health
# checks and scraping keep working while the business API degrades.
_CHAOS_EXEMPT_PREFIXES = ("/health", "/ready", "/metrics", "/chaos")


class ChaosConfig(BaseModel):
    error_rate: float | None = Field(default=None, ge=0, le=1)
    latency_ms: int | None = Field(default=None, ge=0, le=30_000)
    cpu_burn_ms: int | None = Field(default=None, ge=0, le=5_000)
    memory_leak_mb: int | None = Field(default=None, ge=0, le=64)
    dependency_failure: bool | None = None


def _route_template(request: Request) -> str:
    """Return the matched route path (e.g. /api/items/{item_id}) to keep metric
    label cardinality bounded."""
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", "unmatched")
    return "unmatched"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.service_name, version=settings.version)
    app.state.settings = settings
    app.state.chaos = ChaosController()
    app.state.store = InventoryStore()

    metrics.APP_INFO.info(
        {"service": settings.service_name, "version": settings.version, "env": settings.environment}
    )
    metrics.INVENTORY_ITEMS.set(app.state.store.count())

    # ------------------------------------------------------------------ middleware
    @app.middleware("http")
    async def observe(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        route = _route_template(request)
        method = request.method
        chaos: ChaosController = request.app.state.chaos
        state = chaos.state
        exempt = request.url.path.startswith(_CHAOS_EXEMPT_PREFIXES)

        metrics.HTTP_IN_PROGRESS.inc()
        start = time.perf_counter()
        try:
            if not exempt and state.active:
                if state.latency_ms:
                    await asyncio.sleep(state.latency_ms / 1000)
                if state.cpu_burn_ms:
                    chaos.burn_cpu(state.cpu_burn_ms)
                if state.memory_leak_mb:
                    chaos.leak(state.memory_leak_mb)
            if not exempt and chaos.should_fail():
                log.error(
                    "Injected failure",
                    extra={"request_id": request_id, "route": route, "event": "chaos_error"},
                )
                response = JSONResponse({"detail": "Internal server error"}, status_code=500)
            else:
                response = await call_next(request)
        except Exception as exc:  # pragma: no cover - defensive catch-all
            log.exception(
                "Unhandled error",
                extra={"request_id": request_id, "route": route, "error_type": type(exc).__name__},
            )
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        finally:
            metrics.HTTP_IN_PROGRESS.dec()

        elapsed = time.perf_counter() - start
        metrics.HTTP_REQUESTS.labels(method, route, str(response.status_code)).inc()
        metrics.HTTP_LATENCY.labels(method, route).observe(elapsed)
        response.headers["x-request-id"] = request_id

        if request.url.path != "/metrics":  # don't flood logs with scrapes
            level = logging.ERROR if response.status_code >= 500 else logging.INFO
            access_log.log(
                level,
                "request",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": request.url.path,
                    "route": route,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 2),
                    "client": request.client.host if request.client else None,
                    "event": "http_request",
                },
            )
        return response

    # ------------------------------------------------------------- dependencies
    def get_store(request: Request) -> InventoryStore:
        if request.app.state.chaos.state.dependency_failure:
            log.error(
                "inventory-db connection refused (host=inventory-db port=5432)",
                extra={"event": "dependency_error", "error_type": "ConnectionRefusedError"},
            )
            raise DependencyUnavailable("inventory database unavailable")
        return request.app.state.store

    def require_chaos(
        request: Request, x_chaos_token: str | None = Header(default=None)
    ) -> ChaosController:
        cfg: Settings = request.app.state.settings
        if not cfg.chaos_enabled:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        if cfg.chaos_token and not hmac.compare_digest(x_chaos_token or "", cfg.chaos_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid chaos token")
        return request.app.state.chaos

    @app.exception_handler(DependencyUnavailable)
    async def dependency_unavailable(_: Request, exc: DependencyUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    # ------------------------------------------------------------ ops endpoints
    @app.get("/", tags=["ops"])
    def info() -> dict[str, str]:
        return {
            "service": settings.service_name,
            "version": settings.version,
            "env": settings.environment,
        }

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        """Liveness: the process is up and serving."""
        return {"status": "ok", "version": settings.version}

    @app.get("/ready", tags=["ops"])
    def ready(request: Request) -> JSONResponse:
        """Readiness: dependencies are reachable and traffic can be served."""
        if request.app.state.chaos.state.dependency_failure:
            return JSONResponse(
                {"status": "unavailable", "checks": {"inventory-db": "down"}}, status_code=503
            )
        return JSONResponse({"status": "ready", "checks": {"inventory-db": "up"}})

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ------------------------------------------------------------- business API
    @app.get("/api/items", response_model=list[Item], tags=["inventory"])
    def list_items(store: InventoryStore = Depends(get_store)) -> list[Item]:
        return store.list()

    @app.get("/api/items/{item_id}", response_model=Item, tags=["inventory"])
    def get_item(item_id: int, store: InventoryStore = Depends(get_store)) -> Item:
        item = store.get(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        return item

    @app.post(
        "/api/items", response_model=Item, status_code=status.HTTP_201_CREATED, tags=["inventory"]
    )
    def create_item(data: ItemIn, store: InventoryStore = Depends(get_store)) -> Item:
        item = store.create(data)
        metrics.INVENTORY_ITEMS.set(store.count())
        return item

    @app.delete(
        "/api/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["inventory"]
    )
    def delete_item(item_id: int, store: InventoryStore = Depends(get_store)) -> Response:
        if not store.delete(item_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        metrics.INVENTORY_ITEMS.set(store.count())
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # -------------------------------------------------------- failure injection
    @app.get("/chaos", tags=["chaos"])
    def chaos_status(chaos: ChaosController = Depends(require_chaos)) -> dict[str, object]:
        return {**chaos.state.as_dict(), "leaked_bytes": chaos.leaked_bytes}

    @app.post("/chaos", tags=["chaos"])
    def chaos_configure(
        config: ChaosConfig, chaos: ChaosController = Depends(require_chaos)
    ) -> dict[str, object]:
        changes = config.model_dump(exclude_none=True)
        new_state = chaos.configure(**changes)
        log.warning("Chaos configured", extra={"event": "chaos_configured", "chaos": changes})
        return new_state.as_dict()

    @app.delete("/chaos", tags=["chaos"])
    def chaos_reset(chaos: ChaosController = Depends(require_chaos)) -> dict[str, object]:
        new_state = chaos.reset()
        log.warning("Chaos reset", extra={"event": "chaos_reset"})
        return new_state.as_dict()

    log.info("Service started", extra={"event": "startup"})
    return app


app = create_app()
