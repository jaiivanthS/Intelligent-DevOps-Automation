# demo-app

A small inventory REST service. It is the workload that the platform builds,
deploys, monitors and recovers. It ships with **controlled failure injection**
so we can create realistic, labelled incidents for the RCA engine.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8000 --no-access-log
```

Open http://localhost:8000/docs for the interactive API.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Service name, version, environment |
| `GET /health` | Liveness probe |
| `GET /ready` | Readiness probe (fails when the inventory DB is "down") |
| `GET /metrics` | Prometheus metrics |
| `GET/POST /api/items`, `GET/DELETE /api/items/{id}` | Inventory API |
| `GET/POST/DELETE /chaos` | Failure injection (only when `CHAOS_ENABLED=true`) |

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `APP_VERSION` | `0.1.0` | Reported in `/`, `/health`, logs and `app_info` metric. Jenkins sets it to the build tag. |
| `APP_ENV` | `local` | Environment name (local / staging / production) |
| `LOG_LEVEL` | `INFO` | Python log level |
| `CHAOS_ENABLED` | `false` | Expose `/chaos` endpoints |
| `CHAOS_TOKEN` | – | If set, `/chaos` requires header `X-Chaos-Token` |

## Failure injection

```bash
# 30% of API requests fail with 500
curl -X POST localhost:8000/chaos -H "Content-Type: application/json" -d '{"error_rate": 0.3}'
# add 800 ms latency
curl -X POST localhost:8000/chaos -H "Content-Type: application/json" -d '{"latency_ms": 800}'
# simulate the database going down
curl -X POST localhost:8000/chaos -H "Content-Type: application/json" -d '{"dependency_failure": true}'
# back to normal
curl -X DELETE localhost:8000/chaos
```

| Mode | Signature in telemetry |
|---|---|
| `error_rate` | 5xx spike, `Injected failure` ERROR logs |
| `latency_ms` | p95/p99 latency rise, no errors |
| `cpu_burn_ms` | CPU saturation + latency |
| `memory_leak_mb` | Memory grows per request (capped at 512 MB) |
| `dependency_failure` | 503s, readiness fails, `connection refused` logs, `dependency_up=0` |

`/health`, `/ready`, `/metrics` and `/chaos` are never affected by injection.

## Tests & lint

```bash
pytest --cov=app
ruff check .
```

## Metrics

`http_requests_total{method,route,status}`, `http_request_duration_seconds`,
`http_requests_in_progress`, `inventory_items`, `dependency_up{dependency}`,
`chaos_injection_active{mode}`, `chaos_leaked_memory_bytes`, `app_info`,
plus the default process metrics (on Linux).

Logs are one JSON object per line on stdout (`ts, level, msg, service, version,
env, request_id, route, status, duration_ms, event, …`) ready for Loki.
