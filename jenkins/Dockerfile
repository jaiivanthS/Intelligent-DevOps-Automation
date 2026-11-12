# Jenkins controller with everything the pipeline needs:
# Docker CLI (talks to the host daemon through the mounted socket), Python for
# tests, the ECR credential helper, plugins and Configuration-as-Code.
#
# The "lts" tag keeps core and the latest plugins compatible. After a successful
# first build, pin it (e.g. JENKINS_TAG=2.xxx.x-lts-jdk21) for reproducibility.
ARG JENKINS_TAG=lts-jdk21
FROM jenkins/jenkins:${JENKINS_TAG}

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg python3 python3-venv python3-pip \
      amazon-ecr-credential-helper openssh-client jq \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*
USER jenkins

COPY --chown=jenkins:jenkins plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

COPY --chown=jenkins:jenkins casc.yaml /usr/share/jenkins/ref/casc.yaml

ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false" \
    CASC_JENKINS_CONFIG=/usr/share/jenkins/ref/casc.yaml
