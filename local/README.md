# Local mode: the whole platform on Docker Desktop

Runs the same pipeline, monitoring, RCA and recovery loop as the AWS setup, entirely on
one Windows PC, at no cost. Use it for development, demos and report screenshots; move
to AWS ([docs/setup-guide.md](../docs/setup-guide.md)) when you need a real deployment.

## What stands in for AWS

| AWS | Local |
|---|---|
| ECR repository | `registry` container, `localhost:5000/demo-app` |
| App EC2 host (SSH, `/opt/app/appctl.sh`) | `app-host` container: sshd + Docker CLI on the PC's Docker daemon |
| Jenkins EC2 host | `jenkins` container on `devops-net` |
| node-exporter on each host | one `node-exporter` container (reports the Docker Desktop VM) |
| GitHub webhook | none: start builds from Jenkins (GitHub can't reach localhost) |

The Jenkinsfile, `appctl.sh`, the monitoring stack and the platform are unchanged.
Jenkins still deploys over SSH, pulls from a registry, smoke-tests and rolls back.
The only differences are environment values (`APP_HOST=app-host`,
`APP_URL=http://demo-app:8000`, `ECR_REPOSITORY=localhost:5000/demo-app`) and the
override files in this folder.

## Prerequisites

* Windows 10/11 with WSL 2 and **Docker Desktop** running ("Engine running").
* About 8 GB of free RAM and 15 GB of disk for images.
* Free ports: 3000, 5000, 8000, 8080, 8081, 8088, 9090, 9100.

## Start

```powershell
powershell -ExecutionPolicy Bypass -File local\up.ps1
```

The first run takes 10–15 minutes (image builds). It generates, only when missing:

* `jenkins/.env` with a random admin password, and `jenkins/secrets/app_deploy_key`
* `monitoring/.env` with a random Grafana password
* `platform/.env` with a Jenkins API token created through the Jenkins REST API

All of these are git-ignored.

| Service | URL | Login |
|---|---|---|
| Platform website | http://localhost:8081 | none |
| Jenkins | http://localhost:8080 | `admin` / `JENKINS_ADMIN_PASSWORD` in `jenkins/.env` |
| Grafana | http://localhost:3000 | `admin` / `GRAFANA_ADMIN_PASSWORD` in `monitoring/.env` |
| Prometheus | http://localhost:9090 | none |
| Demo app | http://localhost:8088 | none (after the first deployment) |

## First deployment

1. Jenkins → **demo-app** → **Build with Parameters** → **Build**. The first build loads
   the parameters, so if it only shows **Build Now**, click it once and then use
   **Build with Parameters**.
2. Approve at the **Approval** stage (or tick `AUTO_APPROVE`).
3. When the build is green, http://localhost:8088 serves the new version and the
   platform's Pipeline and Deployments pages show the run.

Then follow [docs/demo-script.md](../docs/demo-script.md) for the incident → RCA →
approved rollback loop. Use `http://localhost:8088` wherever it says `http://<app_ip>`.

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File local\down.ps1          # keeps all data
powershell -ExecutionPolicy Bypass -File local\down.ps1 -Purge   # deletes volumes too
```

## Limits

* Everything shares one Docker daemon, so host-level alerts (`HostHighCpu`,
  `HostHighMemory`) describe the Docker Desktop VM, not separate servers.
* cAdvisor on Docker Desktop may report fewer container metrics than on Linux.
* No HTTPS and no webhook. Builds are started by hand.
