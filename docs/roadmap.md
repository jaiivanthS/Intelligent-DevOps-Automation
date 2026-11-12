# Implementation Roadmap

Each step is committed and pushed to GitHub when it is complete.

| # | Step | Deliverables | Status |
|---|---|---|---|
| 1 | Demo app & repository | FastAPI inventory service, `/health` `/ready` `/metrics`, JSON logs, failure injection, unit tests, repo layout | ✅ Done |
| 2 | AWS EC2 & Terraform | VPC, security groups, least-privilege IAM, ECR, EC2 (Jenkins; app + monitoring), Docker bootstrap | ✅ Done |
| 3 | Jenkins CI & Docker build | Dockerfile, Jenkinsfile (checkout, deps, tests, lint, Bandit, Trivy, build, push), Jenkins-in-Docker | ✅ Done |
| 4 | Deployment & smoke tests | Deploy over SSH with Docker Compose, smoke tests, approval gate, auto-rollback on smoke failure, status webhook | ✅ Done |
| 5 | Monitoring | Prometheus, Grafana (provisioned dashboards), Loki + Promtail, alert rules | ✅ Done |
| 6 | Platform website | FastAPI backend (Jenkins/Prometheus/Loki integration, incident collector) + React UI (6 modules) | ✅ Done |
| 7 | AI root-cause analysis | Rule-based baseline, Isolation Forest, XGBoost/Random Forest, RCAEval + synthetic evaluation | ✅ Done (synthetic evaluated; live and RCAEval runs pending deployment/download) |
| 8 | Approval-based recovery & docs | Operator-approved rollback/restart, post-recovery health check, demo script, report | ✅ Done |

All steps are implemented and tested locally. The remaining work needs a running AWS
deployment: a first real pipeline run, the live-demo RCA evaluation, screenshots and
timings for the report. Follow [setup-guide.md](setup-guide.md), then
[demo-script.md](demo-script.md).

Principles: DevOps automation first, AI advisory only (an operator approves
every recovery action), benchmark and live-demo results reported separately.
