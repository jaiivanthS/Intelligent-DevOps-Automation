# Intelligent DevOps Automation Platform

**AI-assisted failure analysis & automated recovery**: a DevOps-first platform
that builds, tests, deploys, monitors and recovers an application on AWS EC2.
Jenkins is the CI/CD engine; AI is an advisory add-on for root-cause analysis.

## Architecture

```
GitHub ─▶ Jenkins ─▶ Build / Test / Scan ─▶ Docker image ─▶ Registry (ECR)
                                                   │
                                                   ▼
                                   AWS EC2 (Docker / Kubernetes) ─▶ demo-app
                                                   │
                         Prometheus + Grafana + Loki ─▶ Incident Collector
                                                   │
                         RCA Engine ─▶ FastAPI backend ─▶ React dashboard
Terraform provisions the infrastructure; Jenkins executes delivery pipelines.
```

## Repository layout

| Path | Contents | Status |
|---|---|---|
| `demo-app/` | Python FastAPI inventory service with metrics, JSON logs and failure injection | ✅ Step 1 |
| `infra/terraform/` | AWS VPC, security groups, IAM, ECR, EC2 ([setup guide](infra/terraform/README.md)) | ✅ Step 2 |
| `jenkins/`, `Jenkinsfile` | Jenkins-as-code and CI/CD pipeline ([guide](jenkins/README.md)) | ✅ Steps 3–4 |
| `deploy/` | App-host compose file, release controller (`appctl.sh`), smoke tests ([guide](deploy/README.md)) | ✅ Step 4 |
| `monitoring/` | Prometheus, Alertmanager, Grafana, Loki, Promtail, cAdvisor, alert rules, dashboards ([guide](monitoring/README.md)) | ✅ Step 5 |
| `platform/backend/` | FastAPI platform API + incident collector ([guide](platform/README.md)) | ✅ Step 6 |
| `platform/frontend/` | React website: Dashboard, Pipeline, Deployments, Monitoring, Logs, Incidents, Recovery | ✅ Step 6 |
| `rca/` | Root-cause analysis models and evaluation | Step 7 |
| `docs/` | Roadmap, setup guide, report material | ongoing |

See [docs/roadmap.md](docs/roadmap.md) for the step-by-step plan.

## Quick start (demo app)

```bash
cd demo-app
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --port 8000 --no-access-log
```
