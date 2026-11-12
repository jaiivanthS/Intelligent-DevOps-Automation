#!/usr/bin/env bash
# Start the monitoring stack on the app host.
#   ./setup.sh             create .env (random Grafana password), write scrape targets, start
#   ./setup.sh --reload    reload Prometheus config/rules without restarting
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--reload" ]]; then
  curl -fsS -X POST http://localhost:9090/-/reload && echo "Prometheus reloaded"
  exit 0
fi

# Shared network used by demo-app, the monitoring stack and the platform.
docker network inspect devops-net >/dev/null 2>&1 || docker network create devops-net

if [[ ! -f .env ]]; then
  password="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  public_ip=""
  if token="$(curl -fsS -m 2 -X PUT http://169.254.169.254/latest/api/token \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null)"; then
    public_ip="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: ${token}" \
        http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
  fi
  host="${public_ip:-localhost}"
  (umask 077 && cat > .env <<EOF
GRAFANA_ADMIN_PASSWORD=${password}
GRAFANA_ROOT_URL=http://${host}:3000
PROMETHEUS_EXTERNAL_URL=http://${host}:9090
LOADGEN_RPS=2
EOF
  )
  echo "Grafana admin password saved in $(pwd)/.env"
fi

# Point the Jenkins scrape targets at the Jenkins host's private IP from Terraform.
if [[ -f /etc/devops-platform.env ]]; then
  # shellcheck disable=SC1091
  source /etc/devops-platform.env
  if [[ -n "${JENKINS_PRIVATE_IP:-}" ]]; then
    sed -i "s|\"[0-9.]*:8080\"|\"${JENKINS_PRIVATE_IP}:8080\"|" prometheus/targets/jenkins.yml
    sed -i "s|\"[0-9.]*:9100\"|\"${JENKINS_PRIVATE_IP}:9100\"|" prometheus/targets/node-jenkins.yml
  fi
fi

docker compose up -d
echo
echo "Grafana:    $(grep '^GRAFANA_ROOT_URL=' .env | cut -d= -f2-)   (user: admin)"
echo "Prometheus: $(grep '^PROMETHEUS_EXTERNAL_URL=' .env | cut -d= -f2-)"
