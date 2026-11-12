"""Platform API configuration (environment variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "platform.db"
    # Upstream systems (all optional: the UI shows "unavailable" for anything unreachable)
    jenkins_url: str = ""
    jenkins_user: str = ""
    jenkins_token: str = ""
    jenkins_job: str = "demo-app"
    prometheus_url: str = ""
    loki_url: str = ""
    alertmanager_url: str = ""
    app_url: str = ""  # demo-app base URL, e.g. http://demo-app:8000
    app_state_dir: str = ""  # appctl.sh state (/opt/app/state mounted read-only)
    service_name: str = "demo-app"
    # If set, POST /api/events/* and /api/alerts/* require header X-Platform-Token.
    ingest_token: str = ""
    upstream_timeout: float = 5.0
    # A new alert joins an open incident of the same service if one exists.
    cors_origins: tuple[str, ...] = ()


def get_settings() -> Settings:
    env = os.getenv
    return Settings(
        db_path=env("PLATFORM_DB", "platform.db"),
        jenkins_url=env("JENKINS_URL", "").rstrip("/"),
        jenkins_user=env("JENKINS_USER", ""),
        jenkins_token=env("JENKINS_TOKEN", ""),
        jenkins_job=env("JENKINS_JOB", "demo-app"),
        prometheus_url=env("PROMETHEUS_URL", "").rstrip("/"),
        loki_url=env("LOKI_URL", "").rstrip("/"),
        alertmanager_url=env("ALERTMANAGER_URL", "").rstrip("/"),
        app_url=env("APP_URL", "").rstrip("/"),
        app_state_dir=env("APP_STATE_DIR", ""),
        service_name=env("SERVICE_NAME", "demo-app"),
        ingest_token=env("INGEST_TOKEN", ""),
        upstream_timeout=float(env("UPSTREAM_TIMEOUT", "5")),
        cors_origins=tuple(o for o in env("CORS_ORIGINS", "").split(",") if o),
    )
