"""Structured JSON logging to stdout, so Promtail/Loki can parse every field."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from .config import Settings

# Extra attributes we copy from a LogRecord into the JSON line when present.
_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "route",
    "status",
    "duration_ms",
    "client",
    "event",
    "chaos",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._static = {
            "service": settings.service_name,
            "version": settings.version,
            "env": settings.environment,
        }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **self._static,
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(settings))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Route uvicorn's own logs through the same JSON handler; our middleware
    # writes the access log, so uvicorn's access logger is silenced.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
