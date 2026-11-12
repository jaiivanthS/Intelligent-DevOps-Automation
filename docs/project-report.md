# Intelligent DevOps Automation Platform: Project Report

*AI-assisted failure analysis and automated recovery. DevOps first, on AWS EC2.*

> This report is a structured draft. Sections marked **[fill in]** need results you
> can only produce on the deployed system (live-demo evaluation, screenshots,
> timings).

## 1. Introduction

Build, deployment and incident handling are often manual and spread across many
tools. Monitoring shows symptoms, but engineers still find the root cause by hand,
and recovery is slow and inconsistent. This project builds one web platform that
automates the delivery lifecycle (build, test, scan, deploy, monitor, recover), with
an explainable, advisory AI component for root-cause analysis (RCA).

**Objectives**, met as follows:
* CI/CD with Jenkins and GitHub: a webhook-triggered pipeline with quality and security gates.
* Infrastructure as code with Terraform: VPC, security groups, IAM, ECR and EC2.
* Containerisation with Docker, deployed to EC2 with automatic rollback.
* Monitoring with Prometheus, Grafana and Loki, plus alerting.
* AI-assisted RCA with safe, operator-approved rollback.
* One interactive website to manage and observe the workflow.

## 2. System architecture

See [architecture.md](architecture.md) for the diagrams and design decisions. Summary:
* **Jenkins host:** CI/CD and the only privileged path to production.
* **App host:** the application, the observability stack and the platform website.
* **AWS:** an immutable-tag ECR registry and least-privilege IAM roles.

## 3. Implementation

| Area | Implementation | Code |
|---|---|---|
| Demo application | FastAPI inventory service, Prometheus metrics, JSON logs, controlled fault injection (5 modes) | `demo-app/` |
| Infrastructure | Terraform: VPC, SGs with an admin-CIDR guard, IAM (push/pull split), ECR (immutable, scan on push), 2× EC2 (IMDSv2, encrypted gp3) | `infra/terraform/` |
| CI | Jenkinsfile: pytest and coverage, ruff, Bandit, pip-audit, Trivy IaC; Docker build, Trivy image gate, container smoke test, ECR push | `Jenkinsfile` |
| CD | Approval gate, SSH deploy via `appctl.sh`, post-deploy smoke test, automatic rollback, promotion | `deploy/` |
| Observability | Prometheus (14 alerts, 4 recording rules), Alertmanager (inhibition), Loki/Promtail, Grafana dashboards as code | `monitoring/` |
| Platform | FastAPI aggregator, incident collector with evidence snapshots, React UI (7 pages) | `platform/` |
| RCA | Features, rule baseline, Random Forest, Isolation Forest, explanations, evaluation tooling | `rca/` |
| Recovery | Request → approve → Jenkins recovery job → health check → callback, with an audit trail | `platform/backend/app/recovery.py`, `jenkins/recovery.Jenkinsfile` |

**Engineering practices:**
* 69 automated tests: demo-app 18, platform 37, RCA 14
* all configuration as code (Terraform, JCasC, Grafana provisioning)
* secrets generated on the hosts and never committed
* each roadmap step committed separately

## 4. AI root-cause analysis

* **Inputs:** an evidence snapshot taken when an incident opens:
  * 30 minutes of key metrics
  * error and warning log summary
  * recent deployments
  * alert categories
* **Features:** 26, shared by training and serving.
* **Models:**
  * a rule-based baseline
  * a Random Forest classifier over 7 causes
  * an Isolation Forest anomaly detector, calibrated to 2% false alarms
* **Output:** ranked causes with confidence, human-readable evidence, suggested checks and a suggested action. The action is advisory and constrained, for example no rollback without a last-good image, and none for dependency failures.

### 4.1 Evaluation

Results are reported **separately by data source**, as the proposal requires.

**(a) Synthetic incidents.** Full report: [`rca/reports/synthetic_evaluation.md`](../rca/reports/synthetic_evaluation.md).

| Method | AC@1 standard | AC@1 hard | Macro-F1 hard |
|---|---|---|---|
| Rule-based | 91.6% | 71.5% | 72.1% |
| Random Forest | 99.4% | 97.9% | 97.9% |
| Gradient boosting | 99.7% | 98.5% | 98.5% |
| XGBoost | 99.6% | 98.2% | 98.2% |

* Learned models beat hand-written rules, mainly on gradual or confounded faults. Hard-set recall for memory leak is 36% with rules vs 97% with ML.
* Ablation: metrics alone drop accuracy to 85.5%, so combining telemetry with deployment context matters most.
* Isolation Forest scores ROC AUC 0.91–0.92.
* **The synthetic accuracy is optimistic by construction**, because the generator links causes to measured signals.

**(b) Live demo on the deployed system.** **[fill in]** Run `python -m rca_engine.live export/evaluate`
after injecting about 10 faults per mode. Report AC@1/AC@3 for rules vs model and a
confusion table. Discuss failure cases.

**(c) RCAEval benchmark.** **[fill in, optional]** Use the adapter in `rca_engine/benchmarks/rcaeval.py`.
* Task mapping: fault-type classification on the root-cause service. This is not service localisation, so don't compare with published Avg@5.
* License: MIT (README) vs CC BY 4.0 (Zenodo). Cite and attribute.
* The schema must be inspected first (`--inspect`).

## 5. Results and demonstration

**[fill in]** Screenshots are needed of:
* the pipeline run, with stages and gates
* Grafana during an injected fault
* the incident with its RCA panel
* the recovery approval and result
* the incident audit trail

Measure:
* pipeline duration (commit to production)
* MTTD: fault to alert to incident
* RCA latency
* MTTR: approval to healthy

Compare these with a manual baseline.

## 6. Research focus

* **Contribution (engineering):** an end-to-end, reproducible DevOps automation and incident workflow.
* **Research angle:** telemetry-informed, explainable root-cause ranking connected to *safe*, human-approved recovery. That includes:
  * leakage-free ground truth from controlled fault injection
  * evidence snapshots linked to releases
  * recovery actions constrained by release history
* **Novelty claims** need a literature review first, comparing with BARO, CIRCA, RCD and others from RCAEval, and with AIOps platforms. **[fill in]**

## 7. Limitations and future work

* Single service on two EC2 hosts. Kubernetes (rollouts, probes, HPA) and multi-service localisation are next.
* HTTP only, and the UI has no SSO. Add an ALB with TLS and OIDC.
* Synthetic training data. Retrain with live-labelled incidents (`train --live`) and test on RCAEval.
* SQLite store. Move to Postgres for multi-instance use.

## 8. Conclusion

**[fill in]** Two to three sentences restating the outcome. DevOps automation comes first; AI is an explainable, advisory enhancement with human-approved recovery.

## References

* Pham, L. et al. *RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data.* 2025.
* Liu, F. T., Ting, K. M., Zhou, Z.-H. *Isolation Forest.* ICDM 2008.
* Breiman, L. *Random Forests.* Machine Learning 45, 2001.
* Tool documentation: Jenkins, Terraform, Prometheus, Grafana Loki, FastAPI, React.
