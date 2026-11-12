#!/usr/bin/env bash
# Build and start the platform website on the app host.
#   ./setup.sh        create .env if missing, build images, start
set -euo pipefail
cd "$(dirname "$0")"

docker network inspect devops-net >/dev/null 2>&1 || docker network create devops-net
sudo install -d -o "$(id -u)" -g "$(id -g)" /opt/app/state 2>/dev/null || mkdir -p /opt/app/state

if [[ ! -f .env ]]; then
  cp .env.example .env
  if [[ -f /etc/devops-platform.env ]]; then
    # shellcheck disable=SC1091
    source /etc/devops-platform.env
    if [[ -n "${JENKINS_PRIVATE_IP:-}" ]]; then
      sed -i "s|^JENKINS_URL=.*|JENKINS_URL=http://${JENKINS_PRIVATE_IP}:8080|" .env
    fi
  fi
  chmod 600 .env
  echo "Created .env. Add JENKINS_TOKEN (Jenkins > admin > Security > API Token) and re-run."
fi

docker compose up -d --build
echo "Platform UI:  http://<app_public_ip>:8081"
