# Platform website (FastAPI + React)

This is the single place to manage and observe the delivery workflow. It runs on
the **app host** on the shared `devops-net` network.

```
React UI (nginx :8081) ──/api──▶ platform-api (FastAPI :8000) ──▶ Jenkins API  (builds, stages, tests, console)
                                        │  ▲                     ├─▶ Prometheus   (metrics, targets)
                                        │  │                     ├─▶ Loki         (logs)
                                        │  │                     ├─▶ Alertmanager (active alerts)
                                        │  │                     ├─▶ demo-app     (version, readiness)
                                        │  │                     └─▶ /opt/app/state (appctl release state, read-only)
                                        │  ├── POST /api/events/jenkins       ◀── Jenkinsfile notifyPlatform()
                                        │  └── POST /api/alerts/alertmanager  ◀── Alertmanager webhook
                                        └── SQLite: events, alerts, incidents (+ evidence, RCA, ground truth)
```

## Modules

| Page | Shows |
|---|---|
| **Dashboard** | Service health (version, readiness), request rate, error ratio, p95 latency, open incidents, firing alerts, latest builds, current release, recent pipeline events |
| **Pipeline** | Jenkins builds with parameters, stage view, test report (failures expandable), console log tail, and the platform events for each build. If the Jenkins API is unreachable, it falls back to the events Jenkins pushed. |
| **Deployments** | Environment, deployed and last-good image, running-version consistency check, app-host release audit trail, pipeline deployment events |
| **Monitoring** | Request rate, error ratio, p95, memory, CPU and dependency charts (15 minutes to 24 hours), firing alerts, scrape-target health |
| **Logs** | Loki search with filters for level, event type, time range and free text. The page shows the generated LogQL. |
| **Incidents** | Correlated incidents with alerts, an evidence snapshot (metric baseline → now with sparklines, top error messages, deployments in the previous hour), RCA results (step 7) and experiment ground truth. Each incident can be acknowledged, resolved, reopened or have its evidence refreshed. |
| **Recovery** | Request a rollback or restart (with reason, optionally linked to an incident), an approval queue (approve or reject, optional token and four-eyes rule), live status, and a history showing smoke-test and platform health checks |

Every upstream is optional. Anything unreachable shows **"unavailable"** in place
and never breaks the page.

## Incident collector

* A firing alert **joins the open incident of the same service**, or opens a new
  one. Severity escalates to the worst alert.
* An incident **resolves automatically** when all its alerts resolve.
* When an incident opens, an **evidence snapshot** is collected in the background:
  * 30 minutes of key metrics, with baseline, current value and peak
  * the top error and warning log messages from the last 15 minutes
  * deployments from the last hour
  * the release state
* `ChaosInjectionActive` alerts (`ground_truth="true"`) never open incidents and
  are never used as evidence. They are stored as **ground truth** to evaluate the
  RCA engine.
* After the evidence is collected, the **RCA engine** ([rca/](../rca/README.md)) ranks
  the probable causes and stores them. The result includes the confidence, a "why"
  explanation, suggested checks, a suggested action, a comparison with the
  rule-based baseline, and an anomaly score.
  `POST /api/incidents/{id}/rca` re-runs it.

## Approval-based recovery

```
request (name, reason) ─▶ pending_approval ─approve (name [+ token]) ─▶ Jenkins "recovery" job
                              │                                            │ appctl rollback/restart
                       reject / 30 min expiry                              │ smoke test (expects target version)
                                                                           ▼
                         succeeded | failed ◀── POST /result ── platform health and version check
```

* The platform never touches the app host itself. The approved action runs in the
  Jenkins `recovery` job (`jenkins/recovery.Jenkinsfile`), which uses the same deploy key
  and audit trail as deployments.
* **Guardrails:**
  * Only one action can be active at a time.
  * Rollback targets must come from the release history, and Jenkins re-checks them against the ECR repository.
  * Unapproved requests expire after 30 minutes, and lost runs time out after 20 minutes.
* **Settings** (`.env`):
  * `RECOVERY_APPROVAL_TOKEN`: a secret that approvers must enter
  * `REQUIRE_DISTINCT_APPROVER=true`: the four-eyes rule
  * `JENKINS_USER`/`JENKINS_TOKEN` need permission to build the `recovery` job
* Every step is recorded on the action and appended to the linked incident's notes.
  The incident's RCA links to a pre-filled request for its suggested action.

## Run on the app host

```bash
cd Intelligent-DevOps-Automation/platform
./setup.sh              # creates .env (JENKINS_URL from Terraform), builds, starts
# add a Jenkins API token to .env (JENKINS_TOKEN=...), then:
docker compose up -d
```

Open `http://<app_public_ip>:8081`. Ports 8081 and 8000 are restricted to `admin_cidrs`.
Jenkins can also reach port 8000 to send pipeline events.

## Develop locally

```bash
cd platform/backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                # 19 tests, fake upstreams via httpx.MockTransport
set APP_URL=http://127.0.0.1:8001     # optional: point at a running demo-app
uvicorn app.main:app --port 8000

cd ../frontend
npm install
npm run dev                           # http://localhost:5173, proxies /api to :8000
```

## API summary

| Method and path | Purpose |
|---|---|
| `GET /api/dashboard` | Aggregated overview |
| `GET /api/pipeline/builds`, `/builds/{n}`, `/builds/{n}/log` | Jenkins builds, stages and tests, console |
| `GET /api/deployments` | Release state, running version, history |
| `GET /api/monitoring?minutes=` | Metric series, targets, alerts |
| `GET /api/logs?level=&event=&search=&minutes=` | Loki query (validated or escaped, no raw LogQL from clients) |
| `GET /api/incidents[?status=active]`, `GET /api/incidents/{id}` | Incidents |
| `POST /api/incidents/{id}/acknowledge` \| `resolve` \| `reopen` \| `evidence/refresh` | Incident workflow |
| `POST /api/events/jenkins`, `POST /api/alerts/alertmanager` | Ingest (optional `X-Platform-Token`) |
| `POST /api/incidents/{id}/rca` | Re-run RCA |
| `GET /api/recovery/options`, `GET /api/recovery/actions[/{id}]` | Recovery state and history |
| `POST /api/recovery/actions` · `/{id}/approve` · `/{id}/reject` | Request and decide |
| `POST /api/recovery/actions/{id}/result` | Jenkins callback (optional `X-Platform-Token`) |
