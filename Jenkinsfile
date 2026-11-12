// CI/CD pipeline for demo-app:
//   test -> quality & security -> build -> scan -> container smoke -> publish
//   -> approval -> deploy -> post-deploy smoke test -> promote  (auto-rollback on failure)
//
// Expected Jenkins environment (set by jenkins/casc.yaml from .env):
//   AWS_REGION, ECR_REGISTRY, ECR_REPOSITORY  empty -> CI only, no push
//   APP_HOST                                  empty -> no deployment stages
//   PLATFORM_API_URL                          empty -> no status events sent
// Credential: app-host-ssh (SSH key for ubuntu@APP_HOST).

def deployEnabled() {
  return (env.ECR_REPOSITORY?.trim() && env.APP_HOST?.trim()) as boolean
}

// Run appctl.sh on the app host; returns the exit code.
def appctl(String args) {
  sshagent(credentials: ['app-host-ssh']) {
    return sh(returnStatus: true, script: """
      ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "ubuntu@\$APP_HOST" \
        "APPCTL_ACTOR=jenkins-\$BUILD_NUMBER /opt/app/appctl.sh ${args}"
    """)
  }
}

// Send a pipeline/deployment event to the platform API. Never fails the build.
def notifyPlatform(String event, String status, Map extra = [:]) {
  if (!env.PLATFORM_API_URL?.trim()) {
    return
  }
  def payload = [
    event      : event,
    status     : status,
    job        : env.JOB_NAME,
    build      : env.BUILD_NUMBER,
    build_url  : env.BUILD_URL,
    git_commit : env.GIT_COMMIT ?: '',
    image_tag  : env.IMAGE_TAG ?: '',
    environment: env.TARGET_ENV ?: '',
  ] + extra
  writeJSON file: '.platform-event.json', json: payload
  sh(returnStatus: true, script: '''
    curl -fsS -m 5 -X POST -H "Content-Type: application/json" \
      --data @.platform-event.json "$PLATFORM_API_URL/api/events/jenkins" >/dev/null \
      || echo "platform notification failed (ignored)"
  ''')
}

pipeline {
  agent any

  parameters {
    choice(name: 'DEPLOY_ENV', choices: ['production', 'staging'],
           description: 'APP_ENV label for the deployment. production requires manual approval.')
    booleanParam(name: 'AUTO_APPROVE', defaultValue: false,
                 description: 'Skip the approval gate (use for demos only).')
  }

  options {
    timestamps()
    timeout(time: 60, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
    disableConcurrentBuilds()
  }

  environment {
    APP_DIR      = 'demo-app'
    REPORTS      = 'demo-app/reports'
    TRIVY_IMAGE  = 'aquasec/trivy:latest'   // scanner stays current; vulnerability DB is cached
    PIP_DISABLE_PIP_VERSION_CHECK = '1'
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
        script {
          def shortSha = sh(script: 'git rev-parse --short=8 HEAD', returnStdout: true).trim()
          env.GIT_SHORT   = shortSha
          env.IMAGE_TAG   = "${env.BUILD_NUMBER}-${shortSha}"
          env.LOCAL_IMAGE = "demo-app:${env.IMAGE_TAG}"
          env.SMOKE_NAME  = "ci-smoke-${env.BUILD_NUMBER}"
          // params are null on a job's very first run, before Jenkins has read this file.
          env.TARGET_ENV  = params.DEPLOY_ENV ?: 'production'
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${shortSha}"
          notifyPlatform('pipeline', 'started')
        }
        sh 'mkdir -p "$REPORTS"'
      }
    }

    stage('Install dependencies') {
      steps {
        dir(env.APP_DIR) {
          sh '''
            python3 -m venv .venv
            . .venv/bin/activate
            pip install -q --upgrade pip
            pip install -q -r requirements-dev.txt
          '''
        }
      }
    }

    stage('Quality & security gates') {
      parallel {
        stage('Unit tests') {
          steps {
            dir(env.APP_DIR) {
              sh '''
                . .venv/bin/activate
                pytest -p no:cacheprovider \
                  --junitxml=reports/junit-tests.xml \
                  --cov=app --cov-report=xml:reports/coverage.xml --cov-report=term
              '''
            }
          }
        }
        stage('Lint (ruff)') {
          steps {
            dir(env.APP_DIR) {
              sh '''
                . .venv/bin/activate
                ruff check --output-format=junit --output-file=reports/junit-ruff.xml . \
                  || { ruff check .; exit 1; }
              '''
            }
          }
        }
        stage('SAST (bandit)') {
          steps {
            dir(env.APP_DIR) {
              sh '''
                . .venv/bin/activate
                bandit -r app -f json -o reports/bandit.json || { bandit -r app; exit 1; }
              '''
            }
          }
        }
        stage('Dependency audit (pip-audit)') {
          steps {
            dir(env.APP_DIR) {
              sh '''
                . .venv/bin/activate
                pip-audit -r requirements.txt --progress-spinner off -f json -o reports/pip-audit.json \
                  || { pip-audit -r requirements.txt --progress-spinner off; exit 1; }
              '''
            }
          }
        }
        stage('IaC scan (trivy config)') {
          steps {
            // Report-only: findings are archived for review, they don't block the build.
            // --volumes-from shares this Jenkins container's workspace with the scanner.
            sh '''
              docker run --rm --volumes-from "$(hostname)" -w "$WORKSPACE" \
                -v trivy-cache:/root/.cache/ "$TRIVY_IMAGE" config --quiet \
                --severity HIGH,CRITICAL --exit-code 0 infra/terraform \
                > "$REPORTS/trivy-iac.txt"
              cat "$REPORTS/trivy-iac.txt"
            '''
          }
        }
      }
    }

    stage('Build image') {
      steps {
        sh '''
          docker build \
            --build-arg APP_VERSION="$IMAGE_TAG" \
            --build-arg GIT_COMMIT="$GIT_COMMIT" \
            --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            -t "$LOCAL_IMAGE" "$APP_DIR"
        '''
      }
    }

    stage('Image scan (trivy)') {
      steps {
        sh '''
          scan() {
            docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
              -v trivy-cache:/root/.cache/ "$TRIVY_IMAGE" image --quiet --ignore-unfixed "$@" "$LOCAL_IMAGE"
          }
          # Full report (HIGH+CRITICAL) for the record...
          scan --severity HIGH,CRITICAL --exit-code 0 > "$REPORTS/trivy-image.txt"
          cat "$REPORTS/trivy-image.txt"
          # ...but only fixable CRITICAL vulnerabilities fail the build.
          scan --severity CRITICAL --exit-code 1 > /dev/null
        '''
      }
    }

    stage('Container smoke test') {
      steps {
        sh '''
          docker run -d --name "$SMOKE_NAME" "$LOCAL_IMAGE"
          for i in $(seq 1 30); do
            status="$(docker inspect -f '{{.State.Health.Status}}' "$SMOKE_NAME")"
            [ "$status" = healthy ] && break
            [ "$status" = unhealthy ] && break
            sleep 2
          done
          echo "container health: $status"
          docker logs "$SMOKE_NAME" | tail -n 20
          test "$status" = healthy
          docker exec "$SMOKE_NAME" python -c "
import json, urllib.request
for path in ('/health', '/ready', '/api/items', '/metrics'):
    r = urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=3)
    assert r.status == 200, (path, r.status)
    print('OK', path)
info = json.load(urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3))
assert info['version'] == '$IMAGE_TAG', info
print('version', info['version'])
"
        '''
      }
      post {
        always {
          sh 'docker rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true'
        }
      }
    }

    stage('Publish to ECR') {
      // The job only builds */main (see casc.yaml); `branch` conditions need a multibranch job.
      when {
        expression { env.ECR_REPOSITORY?.trim() }
      }
      steps {
        sh '''
          # Per-build Docker config: authenticate to ECR through the EC2 instance role.
          export DOCKER_CONFIG="$WORKSPACE/.docker-ci"
          mkdir -p "$DOCKER_CONFIG"
          printf '{ "credHelpers": { "%s": "ecr-login" } }\n' "$ECR_REGISTRY" > "$DOCKER_CONFIG/config.json"

          docker tag "$LOCAL_IMAGE" "$ECR_REPOSITORY:$IMAGE_TAG"
          docker push "$ECR_REPOSITORY:$IMAGE_TAG"
          echo "Published $ECR_REPOSITORY:$IMAGE_TAG"
        '''
      }
    }

    stage('Approval') {
      when {
        expression { deployEnabled() && env.TARGET_ENV == 'production' && !params.AUTO_APPROVE }
      }
      steps {
        script { notifyPlatform('approval', 'waiting') }
        timeout(time: 30, unit: 'MINUTES') {
          input message: "Deploy ${env.IMAGE_TAG} to ${env.TARGET_ENV}?", ok: 'Deploy'
        }
        script { notifyPlatform('approval', 'approved') }
      }
    }

    stage('Deploy') {
      when { expression { deployEnabled() } }
      steps {
        script { notifyPlatform('deploy', 'started') }
        sshagent(credentials: ['app-host-ssh']) {
          sh '''
            scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
              deploy/app/docker-compose.yml deploy/app/appctl.sh "ubuntu@$APP_HOST:/opt/app/"
            ssh -o ConnectTimeout=10 "ubuntu@$APP_HOST" chmod +x /opt/app/appctl.sh
          '''
        }
        script {
          // appctl restores the last good image by itself if the new container never gets healthy.
          def rc = appctl("deploy '${env.ECR_REPOSITORY}:${env.IMAGE_TAG}' '${env.TARGET_ENV}'")
          if (rc != 0) {
            notifyPlatform('deploy', 'failed', [detail: 'container did not become healthy; last good image restored'])
            error('Deployment failed: new container did not become healthy (last good image restored).')
          }
          notifyPlatform('deploy', 'success')
        }
      }
    }

    stage('Post-deploy smoke test') {
      when { expression { deployEnabled() } }
      steps {
        script {
          def rc = sh(returnStatus: true, script: '''
            python3 deploy/scripts/smoke_test.py "http://$APP_HOST" "$IMAGE_TAG" --timeout 60 \
              > "$REPORTS/smoke-test.txt" 2>&1
            rc=$?
            cat "$REPORTS/smoke-test.txt"
            exit $rc
          ''')
          if (rc != 0) {
            notifyPlatform('smoke_test', 'failed')
            echo 'Post-deploy smoke test FAILED: rolling back to the last good image'
            def rb = appctl('rollback')
            env.ROLLED_BACK = 'true'
            notifyPlatform('rollback', rb == 0 ? 'success' : 'failed')
            error(rb == 0
              ? 'Post-deploy smoke test failed: rolled back to the last good image.'
              : 'Post-deploy smoke test failed and ROLLBACK FAILED: manual action required.')
          }
          notifyPlatform('smoke_test', 'passed')
        }
      }
    }

    stage('Promote') {
      when { expression { deployEnabled() } }
      steps {
        script {
          if (appctl('promote') != 0) {
            error('Could not mark the release as last known good.')
          }
          notifyPlatform('release', 'promoted')
          currentBuild.description = "deployed ${env.IMAGE_TAG} to ${env.TARGET_ENV}"
        }
      }
    }
  }

  post {
    success {
      script { notifyPlatform('pipeline', 'success') }
    }
    failure {
      script { notifyPlatform('pipeline', 'failed', [rolled_back: env.ROLLED_BACK == 'true']) }
    }
    aborted {
      script { notifyPlatform('pipeline', 'aborted') }
    }
    always {
      junit allowEmptyResults: true, testResults: 'demo-app/reports/junit-*.xml'
      script {
        if (fileExists('demo-app/reports/coverage.xml')) {
          recordCoverage(tools: [[parser: 'COBERTURA', pattern: 'demo-app/reports/coverage.xml']])
        }
      }
      writeFile file: 'demo-app/reports/image.env',
                text: "IMAGE_TAG=${env.IMAGE_TAG ?: ''}\nIMAGE=${env.ECR_REPOSITORY ?: 'demo-app'}:${env.IMAGE_TAG ?: ''}\nGIT_COMMIT=${env.GIT_COMMIT ?: ''}\n"
      archiveArtifacts allowEmptyArchive: true, artifacts: 'demo-app/reports/**'
    }
    cleanup {
      // Keep the CI host's disk in check: drop this build's local image tags.
      sh '''
        docker image rm "$LOCAL_IMAGE" >/dev/null 2>&1 || true
        [ -n "${ECR_REPOSITORY:-}" ] && docker image rm "$ECR_REPOSITORY:$IMAGE_TAG" >/dev/null 2>&1 || true
        rm -rf "$WORKSPACE/.docker-ci"
      '''
    }
  }
}
