# Infrastructure (Terraform, AWS)

Provisions everything the platform runs on in one region and one availability zone.

| Resource | Purpose |
|---|---|
| VPC, public subnet, internet gateway, route table | Isolated network |
| Default security group | Locked down (no rules) |
| `jenkins` security group | SSH + Jenkins UI from your IP; port 8080 from GitHub webhook ranges; Jenkins metrics + node-exporter from the app host |
| `app` security group | Port 80 for the demo app; SSH and port 80 from Jenkins (deploy + smoke tests); Grafana 3000, Prometheus 9090, platform API 8000, platform UI 8081 from your IP only |
| ECR repository `devops-platform/demo-app` | Immutable tags, scan on push, keeps the last 20 images |
| IAM roles + instance profiles | Jenkins can **push** to that single repo; app host can only **pull**. Optional SSM Session Manager. No AWS keys stored on servers. |
| 2 × EC2 (Ubuntu 24.04, gp3 encrypted, IMDSv2) | `jenkins` host and `app` host (app + monitoring), each with an Elastic IP |

Each instance bootstraps on first boot (`templates/bootstrap.sh.tftpl`):
Docker Engine and the Compose plugin, ECR credential helper, 2 GB swap,
node-exporter, Docker log rotation, and `/opt/jenkins` or `/opt/app`.
Progress is logged to `/var/log/bootstrap.log`; `/var/lib/bootstrap.done` marks success.

## Prerequisites

1. An AWS account and an IAM user (or SSO role) allowed to manage EC2, VPC, IAM, and ECR.
2. AWS CLI v2, configured: `aws configure` (or `aws sso login`).
3. Terraform ≥ 1.6.
4. An SSH key pair: `ssh-keygen -t ed25519`.

## Usage

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # then edit: admin_cidrs, ssh_public_key
terraform init
terraform plan -out tfplan
terraform apply tfplan
terraform output                               # URLs, IPs, ECR repository
```

Wait about 3–5 minutes for bootstrap, then check:

```bash
ssh ubuntu@$(terraform output -raw app_public_ip) "test -f /var/lib/bootstrap.done && docker ps"
```

If your public IP changes, update `admin_cidrs` and run `terraform apply` again.

## Cost and cleanup

With default settings (2 × t3.medium, 2 × 30 GB gp3, 2 Elastic IPs) running 24/7,
expect roughly **US$70–80/month** (region-dependent). To keep costs down:

* Stop the instances when you're not using them (`aws ec2 stop-instances ...`).
  The Elastic IPs keep the same addresses. Stopped instances still incur
  small charges for EBS storage and public IPv4 addresses.
* Tear everything down with `terraform destroy` when the demo is over.
  ECR images are deleted too.

## Security notes

* Admin ports are never open to `0.0.0.0/0`; a validation rule rejects it.
* T3 CPU credits are set to `standard` to avoid surprise "unlimited" burst charges.
* `terraform.tfvars`, `*.tfstate`, and keys are git-ignored. For shared or long-lived use,
  move state to S3 (`backend.tf.example`).
* The demo app is plain HTTP. Add an ALB with an ACM certificate, or Caddy, for TLS in a
  production-like setup.
