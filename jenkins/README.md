# Jenkins (CI/CD engine)

Jenkins runs in Docker on the Jenkins EC2 host and is configured entirely
by code. There's no setup wizard and no manual clicking.

| File | Purpose |
|---|---|
| `Dockerfile` | Jenkins LTS plus Docker CLI, Python 3, ECR credential helper, plugins |
| `plugins.txt` | Pipeline, Git/GitHub, JCasC, Job DSL, credentials, SSH agent, JUnit, coverage, Prometheus |
| `casc.yaml` | Admin user, security, global env (`ECR_*`), and the `demo-app` pipeline job (triggered by GitHub push) |
| `docker-compose.yml` | Runs the controller with a persistent `jenkins_home` and the host Docker socket |
| `setup.sh` | Generates `.env` (random admin password, public URL, ECR settings, Docker group id) and starts Jenkins |

## Start Jenkins on the EC2 host

```bash
ssh ubuntu@<jenkins_public_ip>
git clone https://github.com/jaiivanthS/Intelligent-DevOps-Automation.git
cd Intelligent-DevOps-Automation/jenkins
./setup.sh
grep JENKINS_ADMIN_PASSWORD .env      # login password (user: admin)
```

Then open `terraform output jenkins_url`.

On the first run, `setup.sh` also creates a dedicated deploy key. It is stored in
`jenkins/secrets/`, which is git-ignored, and loaded as the `app-host-ssh`
credential. The script prints a one-time command for you to run from your PC.
That command adds the key's public half to the app host's `authorized_keys`.
`APP_HOST` and `PLATFORM_API_URL` are filled in automatically from the
Terraform bootstrap. The app host's private IP is fixed at `10.20.1.20`.

## Connect GitHub

In the GitHub repo, open **Settings → Webhooks → Add webhook** and set:

* **Payload URL:** `terraform output github_webhook_url` (`http://<ip>:8080/github-webhook/`)
* **Content type:** `application/json`
* **Events:** *Just the push event*

Every push to `main` now triggers the `demo-app` job. The repository is public,
so cloning needs no credentials.

## Pipeline ([`../Jenkinsfile`](../Jenkinsfile))

```
Checkout ─▶ Install deps ─▶ ┌ Unit tests + coverage (pytest)      ┐
                            │ Lint (ruff)                         │
                            │ SAST (bandit)                       │ parallel
                            │ Dependency audit (pip-audit)        │
                            └ IaC scan (trivy config, report-only)┘
        ─▶ Build image ─▶ Image scan (trivy: fixable CRITICAL fails)
        ─▶ Container smoke test (healthcheck, /ready, /api, /metrics, version)
        ─▶ Publish to ECR  (tag = <build>-<git sha>, only when ECR_REPOSITORY is set)
        ─▶ Approval (production) ─▶ Deploy ─▶ Post-deploy smoke test ─▶ Promote
                                     └──── on failure: automatic rollback to last good image
```

Build parameters:

* `DEPLOY_ENV`: `production` (requires approval) or `staging`
* `AUTO_APPROVE`: skips the approval gate, for demos

See [`../deploy/README.md`](../deploy/README.md) for details of the release flow.

Reports (JUnit, coverage, bandit, pip-audit, trivy, `image.env`) are archived
on every build. Pushing to ECR uses the EC2 instance role, so no AWS keys are
stored in Jenkins.

## Security notes

* Mounting `/var/run/docker.sock` gives Jenkins root-equivalent access to its
  host. That's why the host runs only CI and its UI is limited to `admin_cidrs`.
* `.env` holds the admin password. It's created with mode `600` and git-ignored.
* The `lts-jdk21` base tag picks up the current LTS. Pin it after your first
  successful build if you need fully reproducible images.
