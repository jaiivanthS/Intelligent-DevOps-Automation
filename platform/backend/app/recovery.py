"""Approval-based recovery.

Flow (every step is recorded, and linked to the incident when one is given):

  request ──▶ pending_approval ──approve──▶ approved ──Jenkins queued──▶ running
                    │                                                     │
             reject / 30 min                       Jenkins "recovery" job runs appctl,
                    ▼                              smoke-tests, calls back /result
            rejected / expired                                            ▼
                                                             succeeded | failed
                                          (no callback within 20 min: timed_out)

The platform itself never touches the app host: the privileged step runs in the
Jenkins recovery job, with the same deploy key and audit trail as deployments.
Rollback targets are limited to images the release history knows about.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .clients import ReleaseState
from .db import Database, dumps, utcnow

ACTIONS = ("rollback", "restart")
ACTIVE = ("approved", "running")
PENDING_TTL = timedelta(minutes=30)
RUNNING_TIMEOUT = timedelta(minutes=20)


class RecoveryError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _ago(iso: str, delta: timedelta) -> bool:
    return datetime.fromisoformat(iso) < datetime.now(UTC) - delta


def _note(c, incident_id: int | None, text: str) -> None:
    if not incident_id:
        return
    row = c.execute("SELECT notes FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        return
    notes = json.loads(row["notes"] or "[]")
    notes.append({"ts": utcnow(), "status": "recovery", "note": text})
    c.execute("UPDATE incidents SET notes = ?, updated_at = ? WHERE id = ?",
              (json.dumps(notes), utcnow(), incident_id))


def expire_stale(db: Database) -> None:
    """Lazy housekeeping on every read: expire old requests, time out lost runs."""
    now = utcnow()
    with db.tx() as c:
        for row in c.execute("SELECT id, incident_id, status, requested_at, started_at, "
                             "decided_at FROM recovery_actions WHERE status IN "
                             "('pending_approval', 'approved', 'running')").fetchall():
            if row["status"] == "pending_approval" and _ago(row["requested_at"], PENDING_TTL):
                c.execute("UPDATE recovery_actions SET status = 'expired', updated_at = ? "
                          "WHERE id = ?", (now, row["id"]))
                _note(c, row["incident_id"], f"Recovery #{row['id']} expired without approval.")
            elif row["status"] in ACTIVE and _ago(row["started_at"] or row["decided_at"],
                                                  RUNNING_TIMEOUT):
                c.execute("UPDATE recovery_actions SET status = 'timed_out', finished_at = ?, "
                          "detail = 'no result from Jenkins within 20 minutes', updated_at = ? "
                          "WHERE id = ?", (now, now, row["id"]))
                _note(c, row["incident_id"], f"Recovery #{row['id']} timed out; check Jenkins.")


def known_images(state: ReleaseState) -> set[str]:
    cur = state.current()
    images = {cur["current_image"], cur["last_good_image"]}
    images |= {h.get("image") for h in state.history(200) if h.get("result") == "success"}
    return {i for i in images if i}


def options(db: Database, state: ReleaseState, jenkins_ready: bool) -> dict[str, Any]:
    expire_stale(db)
    cur = state.current()
    active = db.one("SELECT * FROM recovery_actions WHERE status IN "
                    "('pending_approval', 'approved', 'running') ORDER BY id DESC LIMIT 1")
    blockers = []
    if not jenkins_ready:
        blockers.append("Jenkins is not configured on the platform (JENKINS_URL/USER/TOKEN).")
    if not cur["available"]:
        blockers.append("Release state is not available (is /opt/app/state mounted?).")
    rollback_ok = bool(cur["last_good_image"]) and cur["last_good_image"] != cur["current_image"]
    return {
        "release": cur,
        "active": active,
        "blockers": blockers,
        "rollback": {"available": rollback_ok, "default_target": cur["last_good_image"],
                     "reason": None if rollback_ok else
                     ("no last good image recorded" if not cur["last_good_image"]
                      else "the running image is already the last good image"),
                     "targets": sorted(known_images(state) - {cur["current_image"]})},
        "restart": {"available": bool(cur["current_image"])},
    }


def create(db: Database, state: ReleaseState, *, action: str, target_image: str | None,
           incident_id: int | None, reason: str, requested_by: str) -> dict[str, Any]:
    expire_stale(db)
    if action not in ACTIONS:
        raise RecoveryError(422, f"action must be one of {ACTIONS}")
    cur = state.current()
    if not cur["available"]:
        raise RecoveryError(409, "release state not available; cannot plan a recovery")
    if action == "rollback":
        target_image = target_image or cur["last_good_image"]
        if not target_image:
            raise RecoveryError(409, "no last good image to roll back to")
        if target_image not in known_images(state):
            raise RecoveryError(422, "rollback target must be an image from the release history")
        if target_image == cur["current_image"]:
            raise RecoveryError(409, "that image is already running")
    else:
        target_image = cur["current_image"]
    now = utcnow()
    with db.tx() as c:
        if incident_id is not None and c.execute(
                "SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone() is None:
            raise RecoveryError(404, "incident not found")
        if c.execute("SELECT 1 FROM recovery_actions WHERE status IN "
                     "('pending_approval', 'approved', 'running')").fetchone():
            raise RecoveryError(409, "another recovery action is already pending or running")
        cur_id = c.execute(
            "INSERT INTO recovery_actions (incident_id, action, target_image, from_image, reason, "
            "status, requested_by, requested_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending_approval', ?, ?, ?)",
            (incident_id, action, target_image, cur["current_image"], reason, requested_by,
             now, now)).lastrowid
        _note(c, incident_id, f"{requested_by} requested {action} #{cur_id}: {reason}")
    return get(db, cur_id)


def get(db: Database, action_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM recovery_actions WHERE id = ?", (action_id,))
    if row is None:
        raise RecoveryError(404, "recovery action not found")
    return row


def decide(db: Database, action_id: int, *, approve: bool, by: str, note: str | None,
           require_distinct: bool) -> dict[str, Any]:
    expire_stale(db)
    row = get(db, action_id)
    if row["status"] != "pending_approval":
        raise RecoveryError(409, f"action is {row['status']}, not pending approval")
    if approve and require_distinct and by.strip().lower() == row["requested_by"].strip().lower():
        raise RecoveryError(403, "the approver must be a different person from the requester")
    now = utcnow()
    status = "approved" if approve else "rejected"
    with db.tx() as c:
        c.execute("UPDATE recovery_actions SET status = ?, decided_by = ?, decided_at = ?, "
                  "decision_note = ?, updated_at = ? WHERE id = ?",
                  (status, by, now, note, now, action_id))
        _note(c, row["incident_id"], f"{by} {status} recovery #{action_id}"
                                     + (f": {note}" if note else ""))
    return get(db, action_id)


def mark_running(db: Database, action_id: int, queue_url: str | None) -> dict[str, Any]:
    now = utcnow()
    with db.tx() as c:
        c.execute("UPDATE recovery_actions SET status = 'running', jenkins_queue = ?, "
                  "started_at = ?, updated_at = ? WHERE id = ? AND status = 'approved'",
                  (queue_url, now, now, action_id))
    return get(db, action_id)


def mark_failed(db: Database, action_id: int, detail: str) -> dict[str, Any]:
    now = utcnow()
    row = get(db, action_id)
    with db.tx() as c:
        c.execute("UPDATE recovery_actions SET status = 'failed', detail = ?, finished_at = ?, "
                  "updated_at = ? WHERE id = ?", (detail, now, now, action_id))
        _note(c, row["incident_id"], f"Recovery #{action_id} failed: {detail}")
    return get(db, action_id)


def record_result(db: Database, action_id: int, *, succeeded: bool, detail: str | None,
                  build: str | None, health: dict[str, Any]) -> dict[str, Any]:
    row = get(db, action_id)
    if row["status"] not in ACTIVE:
        raise RecoveryError(409, f"action is {row['status']}; result not expected")
    now = utcnow()
    status = "succeeded" if succeeded else "failed"
    with db.tx() as c:
        c.execute("UPDATE recovery_actions SET status = ?, detail = ?, jenkins_build = ?, "
                  "health = ?, finished_at = ?, updated_at = ? WHERE id = ?",
                  (status, detail, build, dumps(health), now, now, action_id))
        _note(c, row["incident_id"],
              f"Recovery #{action_id} ({row['action']}) {status}"
              + (f": {detail}" if detail else "") + ".")
    return get(db, action_id)


def merge_health(db: Database, action_id: int, extra: dict[str, Any]) -> dict[str, Any]:
    row = get(db, action_id)
    health = {**(row["health"] or {}), **extra}
    with db.tx() as c:
        c.execute("UPDATE recovery_actions SET health = ? WHERE id = ?", (dumps(health), action_id))
    return get(db, action_id)
