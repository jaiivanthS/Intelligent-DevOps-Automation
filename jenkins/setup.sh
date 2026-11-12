#!/usr/bin/env bash
# Prepare and start Jenkins on the Jenkins EC2 host (or any Linux box with Docker).
#   ./setup.sh            # first run: generates .env, builds and starts Jenkins
#   ./setup.sh --rebuild  # rebuild the image after changing plugins/casc
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Creating .env"
  cp .env.example .env

  password="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  sed -i "s|^JENKINS_ADMIN_PASSWORD=.*|JENKINS_ADMIN_PASSWORD=${password}|" .env

  # Public URL: use the instance's public IP when running on EC2 (IMDSv2).
  if token="$(curl -fsS -m 2 -X PUT http://169.254.169.254/latest/api/token \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null)"; then
    ip="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: ${token}" \
        http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
    [[ -n "${ip}" ]] && sed -i "s|^JENKINS_URL=.*|JENKINS_URL=http://${ip}:8080/|" .env
  fi

  # AWS settings written by the Terraform bootstrap script.
  if [[ -f /etc/devops-platform.env ]]; then
    # shellcheck disable=SC1091
    source /etc/devops-platform.env
    sed -i "s|^AWS_REGION=.*|AWS_REGION=${AWS_REGION}|" .env
    sed -i "s|^ECR_REGISTRY=.*|ECR_REGISTRY=${ECR_REGISTRY}|" .env
    sed -i "s|^ECR_REPOSITORY=.*|ECR_REPOSITORY=${ECR_REPOSITORY}|" .env
  fi
  chmod 600 .env
  echo "Admin password saved in $(pwd)/.env (JENKINS_ADMIN_PASSWORD)."
fi

# Group id of the host's Docker socket, so the jenkins user can run docker.
docker_gid="$(stat -c '%g' /var/run/docker.sock)"
sed -i "s|^DOCKER_GID=.*|DOCKER_GID=${docker_gid}|" .env

if [[ "${1:-}" == "--rebuild" ]]; then
  docker compose build --pull
fi
docker compose up -d --build

echo "Jenkins is starting: $(grep '^JENKINS_URL=' .env | cut -d= -f2-)"
echo "Follow logs with: docker compose logs -f jenkins"
