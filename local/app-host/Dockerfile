# Stand-in for the app EC2 host on the local Docker Desktop stack.
# Jenkins SSHes in as "ubuntu" and runs /opt/app/appctl.sh, exactly as it does on AWS.
# appctl drives the Docker daemon of the PC through the mounted socket, so demo-app
# runs as a normal sibling container on devops-net.
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-server bash curl ca-certificates gnupg openssl util-linux \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 -s /bin/bash ubuntu \
 && passwd -l ubuntu \
 && mkdir -p /run/sshd \
 && printf '%s\n' \
      'PasswordAuthentication no' \
      'KbdInteractiveAuthentication no' \
      'PermitRootLogin no' \
      'AllowUsers ubuntu' \
      > /etc/ssh/sshd_config.d/local.conf

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD bash -c '</dev/tcp/127.0.0.1/22' || exit 1
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
