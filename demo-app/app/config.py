"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    service_name: str = "demo-app"
    version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"
    # Failure injection is how we create realistic incidents for the RCA engine.
    # It must be switched on explicitly and should be token-protected outside local dev.
    chaos_enabled: bool = False
    chaos_token: str | None = None


def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "demo-app"),
        version=os.getenv("APP_VERSION", "0.1.0"),
        environment=os.getenv("APP_ENV", "local"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        chaos_enabled=_env_bool("CHAOS_ENABLED", False),
        chaos_token=os.getenv("CHAOS_TOKEN") or None,
    )
