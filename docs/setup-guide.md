# Setup guide: from zero to a running platform on AWS

Total time is about 60–90 minutes. Each step points to the detailed README.

## 0. Prerequisites (your PC)

Git, Terraform 1.6 or later, AWS CLI v2 (`aws configure`), an SSH key (`ssh-keygen -t ed25519`),
and an AWS account. **Costs:** two t3.medium instances run about US$70–80/month if left
on 24/7. Stop them, or `terraform destroy`, when you're not using them.

## 1. Infrastructure ([infra/terraform](../infra/terraform/README.md))

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set admin_cidrs = ["<your-ip>/32"], ssh_public_key
terraform init && terraform apply
terraform output                               # note jenkins_url, app_public_ip, github_webhook_url
```

Wait about 5 minutes for bootstrap (`/var/lib/bootstrap.done` on both hosts).

## 2. Jenkins ([jenkins/](../jenkins/README.md))

```bash
ssh ubuntu@<jenkins_ip>
git clone https://github.com/jaiivanthS/Intelligent-DevOps-Automation.git && cd Intelligent-DevOps-Automation/jenkins
./setup.sh                # prints the deploy-key command for step 3; password is in .env
```

* GitHub: open **Settings → Webhooks → Add webhook**. Set the URL to `terraform output github_webhook_url`, the content type to JSON, and choose push events.
* Jenkins UI: log in as `admin`. Open **admin → Security → API Token → Add new token**. Copy the token for step 5.

## 3. App host: authorise deploys and start monitoring

```bash
# from your PC: the command printed by jenkins/setup.sh
ssh ubuntu@<app_ip> "echo 'ssh-ed25519 AAAA... jenkins-deploy@...' >> ~/.ssh/authorized_keys"

ssh ubuntu@<app_ip>
git clone https://github.com/jaiivanthS/Intelligent-DevOps-Automation.git && cd Intelligent-DevOps-Automation
monitoring/setup.sh       # Grafana password is in monitoring/.env
```

## 4. First deployment

In Jenkins, run the **demo-app** job (**Build with Parameters**: production). Approve
at the **Approval** stage. The pipeline tests, scans, builds and pushes the image,
then deploys, smoke-tests and promotes it. The app is now at `http://<app_ip>/`.

## 5. Platform website ([platform/](../platform/README.md))

```bash
cd ~/Intelligent-DevOps-Automation/platform
./setup.sh                          # creates .env
nano .env                           # JENKINS_TOKEN=<token from step 2>
                                    # optional: RECOVERY_APPROVAL_TOKEN=..., REQUIRE_DISTINCT_APPROVER=true
docker compose up -d --build        # trains the RCA model during the build (~1 min)
```

Open `http://<app_ip>:8081`. Every integration dot in the sidebar should be green.

## 6. Smoke-check the whole loop

Follow [demo-script.md](demo-script.md). It covers a deployment, an injected incident,
RCA, an approved rollback and automatic resolution.

## Troubleshooting

| Symptom | Check |
|---|---|
| Pipeline skips deploy stages | `APP_HOST` and `ECR_REPOSITORY` are empty in `jenkins/.env`. Re-run `setup.sh` on the Jenkins host after bootstrap. |
| Deploy fails with `Permission denied (publickey)` | Step 3's deploy-key command wasn't run. |
| Platform shows "Jenkins unavailable" | `JENKINS_TOKEN` is missing, or the SG rule from app host to Jenkins :8080 is missing (run `terraform apply`). |
| No incidents appear | Check Alertmanager → `platform-api:8000`: `docker logs alertmanager`. Check the platform-api container is on `devops-net`. |
| Recovery stuck in "running" | Open the Jenkins `recovery` job log. After 20 minutes the platform marks it `timed_out`. |
