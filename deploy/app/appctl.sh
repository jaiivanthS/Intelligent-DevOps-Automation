#!/usr/bin/env bash
# Release control for demo-app on the app host. Called by Jenkins over SSH and,
# later, by the platform's recovery workflow.
#
#   appctl.sh deploy <image> [env]   start <image>; if it never becomes healthy,
#                                    restore the last good image and exit 1
#   appctl.sh promote                mark the running image as last known good
#                                    (Jenkins calls this after smoke tests pass)
#   appctl.sh rollback [image]       redeploy [image] or the last known good image
#   appctl.sh restart                restart the container and wait until healthy
#   appctl.sh status                 JSON summary (current, last good, health)
#   appctl.sh history [n]            last n release events (JSON lines)
#
# State lives in $APPCTL_HOME/state (default /opt/app/state):
#   current_image, last_good_image, releases.jsonl
set -euo pipefail

APPCTL_HOME="${APPCTL_HOME:-$(cd "$(dirname "$0")" && pwd)}"
STATE="$APPCTL_HOME/state"
SERVICE=demo-app
WAIT_TIMEOUT="${WAIT_TIMEOUT:-120}"
mkdir -p "$STATE"
cd "$APPCTL_HOME"

log()  { echo "[appctl] $*" >&2; }
now()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
read_state() { cat "$STATE/$1" 2>/dev/null || true; }
write_state() { printf '%s\n' "$2" > "$STATE/$1.tmp" && mv "$STATE/$1.tmp" "$STATE/$1"; }

record() { # action result image [from] [detail]
  printf '{"ts":"%s","action":"%s","result":"%s","image":"%s","from":"%s","detail":"%s","actor":"%s"}\n' \
    "$(now)" "$1" "$2" "$3" "${4:-}" "${5:-}" "${APPCTL_ACTOR:-${USER:-unknown}}" >> "$STATE/releases.jsonl"
}

lock() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$STATE/.lock"
    flock -w 300 9 || { log "another release operation is still running"; exit 75; }
  fi
}

ensure_secrets() {
  if [[ ! -f secrets.env ]]; then
    (umask 077 && printf 'CHAOS_TOKEN=%s\n' "$(openssl rand -hex 16)" > secrets.env)
    log "generated secrets.env (CHAOS_TOKEN)"
  fi
}

# Start the given image and wait for the container healthcheck. Returns non-zero if unhealthy.
run_image() {
  local image="$1" env="${2:-$(read_state app_env)}"
  env="${env:-production}"
  printf 'IMAGE=%s\nAPP_ENV=%s\n' "$image" "$env" > .env
  # Host-specific compose settings (e.g. APP_PORT on the local Docker Desktop stack).
  if [[ -f host.env ]]; then cat host.env >> .env; fi
  write_state app_env "$env"
  docker network inspect devops-net >/dev/null 2>&1 || docker network create devops-net >/dev/null
  # Explicit && chain: `set -e` is suspended when this function is used in an `if`.
  docker compose pull "$SERVICE" \
    && docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" "$SERVICE"
}

cmd_deploy() {
  local image="${1:?usage: appctl.sh deploy <image> [env]}" env="${2:-production}"
  lock; ensure_secrets
  local previous; previous="$(read_state current_image)"
  log "deploying $image (env=$env, previous=${previous:-none})"

  if run_image "$image" "$env"; then
    write_state current_image "$image"
    record deploy success "$image" "$previous"
    log "deployed $image"
    return 0
  fi

  record deploy failed "$image" "$previous" "container did not become healthy"
  docker compose logs --tail 40 "$SERVICE" >&2 || true
  local good; good="$(read_state last_good_image)"
  if [[ -n "$good" ]]; then
    log "restoring last good image $good"
    if run_image "$good"; then
      write_state current_image "$good"
      record auto-restore success "$good" "$image"
    else
      record auto-restore failed "$good" "$image"
    fi
  fi
  return 1
}

cmd_promote() {
  lock
  local current; current="$(read_state current_image)"
  [[ -n "$current" ]] || { log "nothing deployed yet"; return 1; }
  write_state last_good_image "$current"
  record promote success "$current"
  log "marked $current as last known good"
}

cmd_rollback() {
  lock; ensure_secrets
  local current target
  current="$(read_state current_image)"
  target="${1:-$(read_state last_good_image)}"
  [[ -n "$target" ]] || { log "no last good image recorded and none given"; return 1; }
  if [[ "$target" == "$current" && -z "${1:-}" ]]; then
    log "current image is already the last good image ($target); restarting instead"
  fi
  log "rolling back ${current:-none} -> $target"
  if run_image "$target"; then
    write_state current_image "$target"
    record rollback success "$target" "$current"
    log "rollback complete"
  else
    record rollback failed "$target" "$current"
    return 1
  fi
}

cmd_restart() {
  lock
  local current; current="$(read_state current_image)"
  docker compose restart "$SERVICE"
  if docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" "$SERVICE"; then
    record restart success "$current"
  else
    record restart failed "$current"
    return 1
  fi
}

cmd_status() {
  local health
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$SERVICE" 2>/dev/null || echo missing)"
  printf '{"service":"%s","current_image":"%s","last_good_image":"%s","app_env":"%s","health":"%s"}\n' \
    "$SERVICE" "$(read_state current_image)" "$(read_state last_good_image)" "$(read_state app_env)" "$health"
}

cmd_history() {
  tail -n "${1:-20}" "$STATE/releases.jsonl" 2>/dev/null || true
}

case "${1:-}" in
  deploy)   shift; cmd_deploy "$@" ;;
  promote)  shift; cmd_promote ;;
  rollback) shift; cmd_rollback "$@" ;;
  restart)  shift; cmd_restart ;;
  status)   shift; cmd_status ;;
  history)  shift; cmd_history "$@" ;;
  *) sed -n '2,15p' "$0"; exit 64 ;;
esac
