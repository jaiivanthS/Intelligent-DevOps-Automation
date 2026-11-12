// CI pipeline for demo-app: test -> quality & security -> build -> scan -> smoke -> publish.
// Deployment stages are added in step 4.
//
// Expected Jenkins environment (set by jenkins/casc.yaml from .env):
//   AWS_REGION, ECR_REGISTRY, ECR_REPOSITORY  - leave empty to run CI without pushing.

pipeline {
  agent any

  options {
    timestamps()
    timeout(time: 30, unit: 'MINUTES')
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
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${shortSha}"
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
  }

  post {
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
