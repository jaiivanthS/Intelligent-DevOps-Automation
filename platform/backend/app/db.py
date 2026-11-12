"""SQLite persistence for pipeline events, alerts and incidents (standard library only)."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    source      TEXT NOT NULL,
    event       TEXT NOT NULL,
    status      TEXT NOT NULL,
    build       TEXT,
    image_tag   TEXT,
    environment TEXT,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events (ts);

CREATE TABLE IF NOT EXISTS incidents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    service      TEXT NOT NULL,
    title        TEXT NOT NULL,
    severity     TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,          -- open | acknowledged | resolved
    opened_at    TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    resolved_at  TEXT,
    evidence     TEXT,                   -- JSON snapshot collected when opened
    rca          TEXT,                   -- JSON from the RCA engine (step 7)
    ground_truth TEXT,                   -- JSON: injected faults seen during the incident
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS ix_incidents_status ON incidents (status, service);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint  TEXT NOT NULL UNIQUE,
    incident_id  INTEGER REFERENCES incidents (id),
    alertname    TEXT NOT NULL,
    service      TEXT NOT NULL,
    severity     TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,          -- firing | resolved
    ground_truth INTEGER NOT NULL DEFAULT 0,
    starts_at    TEXT,
    ends_at      TEXT,
    labels       TEXT NOT NULL,
    annotations  TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_incident ON alerts (incident_id);
"""

JSON_COLUMNS = {"payload", "evidence", "rca", "ground_truth", "labels", "annotations", "notes"}


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [decode(row) for row in rows]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        self._conn.close()


def decode(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for key in JSON_COLUMNS & out.keys():
        if out[key] is not None:
            out[key] = json.loads(out[key])
    return out


def dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))
