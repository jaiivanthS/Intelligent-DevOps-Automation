"""Thin async clients for the systems the platform observes.

Every client raises UpstreamError on any failure; API routes turn that into an
"unavailable" field instead of failing the whole response.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


class UpstreamError(RuntimeError):
    pass


class Upstream:
    name = "upstream"

    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base = base_url

    @property
    def configured(self) -> bool:
        return bool(self.base)

    async def get_json(self, path: str, **kwargs: Any) -> Any:
        if not self.base:
            raise UpstreamError(f"{self.name} is not configured")
        try:
            resp = await self.http.get(self.base + path, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamError(f"{self.name}: {exc.__class__.__name__}: {exc}") from exc

    async def get_text(self, path: str, **kwargs: Any) -> str:
        if not self.base:
            raise UpstreamError(f"{self.name} is not configured")
        try:
            resp = await self.http.get(self.base + path, **kwargs)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{self.name}: {exc.__class__.__name__}: {exc}") from exc


# ----------------------------------------------------------------------- Jenkins
class Jenkins(Upstream):
    name = "jenkins"

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        super().__init__(http, settings.jenkins_url)
        self.job = settings.jenkins_job
        self.auth = (
            (settings.jenkins_user, settings.jenkins_token) if settings.jenkins_user else None
        )

    async def builds(self, limit: int = 20) -> list[dict[str, Any]]:
        tree = (f"builds[number,result,building,timestamp,duration,displayName,description,url,"
                f"actions[parameters[name,value]]]{{0,{limit}}}")
        data = await self.get_json(f"/job/{self.job}/api/json", params={"tree": tree},
                                   auth=self.auth)
        builds = []
        for b in data.get("builds", []):
            params = {
                p["name"]: p.get("value")
                for a in b.get("actions") or [] if a and "parameters" in a
                for p in a["parameters"]
            }
            builds.append({
                "number": b["number"],
                "display_name": b.get("displayName"),
                "result": "RUNNING" if b.get("building") else (b.get("result") or "UNKNOWN"),
                "started_at_ms": b.get("timestamp"),
                "duration_ms": b.get("duration"),
                "description": b.get("description"),
                "url": b.get("url"),
                "parameters": params,
            })
        return builds

    async def stages(self, number: int) -> list[dict[str, Any]]:
        # Provided by the pipeline-stage-view plugin.
        data = await self.get_json(f"/job/{self.job}/{number}/wfapi/describe", auth=self.auth)
        return [
            {"name": s.get("name"), "status": s.get("status"),
             "duration_ms": s.get("durationMillis"), "started_at_ms": s.get("startTimeMillis")}
            for s in data.get("stages", [])
        ]

    async def tests(self, number: int) -> dict[str, Any]:
        data = await self.get_json(
            f"/job/{self.job}/{number}/testReport/api/json",
            params={"tree": "passCount,failCount,skipCount,duration,"
                            "suites[name,cases[className,name,status,duration,errorDetails]]"},
            auth=self.auth)
        failed = [
            {"suite": s.get("name"), "test": f"{c.get('className')}.{c.get('name')}",
             "error": c.get("errorDetails")}
            for s in data.get("suites", []) for c in s.get("cases", [])
            if c.get("status") in {"FAILED", "REGRESSION"}
        ]
        return {"passed": data.get("passCount", 0), "failed": data.get("failCount", 0),
                "skipped": data.get("skipCount", 0), "duration_s": data.get("duration"),
                "failures": failed[:50]}

    async def log_tail(self, number: int, lines: int = 300) -> str:
        text = await self.get_text(f"/job/{self.job}/{number}/consoleText", auth=self.auth)
        return "\n".join(text.splitlines()[-lines:])


# -------------------------------------------------------------------- Prometheus
class Prometheus(Upstream):
    name = "prometheus"

    async def instant(self, expr: str) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v1/query", params={"query": expr})
        return [{"labels": r["metric"], "value": float(r["value"][1])}
                for r in data["data"]["result"]]

    async def scalar(self, expr: str) -> float | None:
        result = await self.instant(expr)
        return result[0]["value"] if result else None

    async def series(self, expr: str, minutes: int, step: int) -> list[dict[str, Any]]:
        end = time.time()
        data = await self.get_json("/api/v1/query_range", params={
            "query": expr, "start": end - minutes * 60, "end": end, "step": step})
        return [{"labels": r["metric"],
                 "points": [[int(t), float(v)] for t, v in r["values"]]}
                for r in data["data"]["result"]]

    async def targets(self) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v1/targets", params={"state": "active"})
        return [{"job": t["labels"].get("job"), "instance": t["labels"].get("instance"),
                 "health": t.get("health"), "last_error": t.get("lastError") or None}
                for t in data["data"]["activeTargets"]]


# -------------------------------------------------------------------------- Loki
class Loki(Upstream):
    name = "loki"

    async def query(self, logql: str, minutes: int = 60, limit: int = 200) -> list[dict[str, Any]]:
        end_ns = time.time_ns()
        data = await self.get_json("/loki/api/v1/query_range", params={
            "query": logql, "limit": limit, "direction": "backward",
            "start": end_ns - minutes * 60 * 1_000_000_000, "end": end_ns})
        lines = []
        for stream in data["data"]["result"]:
            labels = stream["stream"]
            for ts, line in stream["values"]:
                try:
                    parsed = json.loads(line)
                except ValueError:
                    parsed = None
                lines.append({"ts_ns": int(ts), "labels": labels, "line": line,
                              "json": parsed if isinstance(parsed, dict) else None})
        lines.sort(key=lambda entry: entry["ts_ns"], reverse=True)
        return lines[:limit]


# ------------------------------------------------------------------ Alertmanager
class Alertmanager(Upstream):
    name = "alertmanager"

    async def active(self) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v2/alerts", params={"active": "true"})
        return [{"alertname": a["labels"].get("alertname"), "labels": a["labels"],
                 "annotations": a.get("annotations", {}), "starts_at": a.get("startsAt"),
                 "state": a.get("status", {}).get("state")} for a in data]


# ---------------------------------------------------------------- demo-app & state
class App(Upstream):
    name = "demo-app"

    async def info(self) -> dict[str, Any]:
        info = await self.get_json("/")
        try:
            ready = await self.get_json("/ready")
            info["ready"] = ready.get("status") == "ready"
        except UpstreamError:
            info["ready"] = False
        return info


class ReleaseState:
    """Reads the release state that appctl.sh keeps on the app host."""

    def __init__(self, state_dir: str) -> None:
        self.dir = Path(state_dir) if state_dir else None

    @property
    def configured(self) -> bool:
        return self.dir is not None and self.dir.is_dir()

    def _read(self, name: str) -> str | None:
        if not self.dir:
            return None
        try:
            return (self.dir / name).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def current(self) -> dict[str, Any]:
        return {"current_image": self._read("current_image"),
                "last_good_image": self._read("last_good_image"),
                "app_env": self._read("app_env"),
                "available": self.configured}

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        raw = self._read("releases.jsonl")
        if not raw:
            return []
        out = []
        for line in raw.splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        out.reverse()
        return out
