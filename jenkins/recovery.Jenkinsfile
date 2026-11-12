// Recovery job: executes an operator-APPROVED action requested in the platform UI.
// Triggered only by platform-api (POST /job/recovery/buildWithParameters) after approval.
// Parameters are declared in casc.yaml so the job can be triggered before its first run:
//   ACTION (rollback|restart), TARGET_IMAGE, REQUEST_ID, INCIDENT_ID, APPROVED_BY

def appctl(String args) {
  sshagent(credentials: ['app-host-ssh']) {
    return sh(returnStatus: true, script: """
      ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "ubuntu@\$APP_HOST" \
        "APPCTL_ACTOR='recovery-\$REQUEST_ID by \$APPROVED_BY' /opt/app/appctl.sh ${args}"
    """)
  }
}

def report(String status, String detail) {
  if (!env.PLATFORM_API_URL?.trim() || !(params.REQUEST_ID ==~ /\d+/)) {
    return
  }
  def smoke = null
  if (fileExists('recovery-smoke.txt')) {
    def lines = readFile('recovery-smoke.txt').trim().readLines()
    if (lines) {
      try { smoke = readJSON(text: lines[-1]) } catch (ignored) { smoke = [raw: lines[-1]] }
    }
  }
  writeJSON file: 'recovery-result.json', json: [
    status: status, detail: detail, build: env.BUILD_NUMBER, build_url: env.BUILD_URL,
    smoke_test: smoke,
  ]
  sh(returnStatus: true, script: '''
    set --
    if [ -n "${PLATFORM_INGEST_TOKEN:-}" ]; then set -- -H "X-Platform-Token: $PLATFORM_INGEST_TOKEN"; fi
    curl -fsS -m 10 -X POST -H "Content-Type: application/json" "$@" \
      --data @recovery-result.json "$PLATFORM_API_URL/api/recovery/actions/$REQUEST_ID/result" \
      || echo "could not report result to the platform"
  ''')
}

pipeline {
  agent any
  options {
    timestamps()
    timeout(time: 15, unit: 'MINUTES')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '50'))
  }

  stages {
    stage('Validate request') {
      steps {
        script {
          if (!(params.ACTION in ['rollback', 'restart'])) {
            error "Unsupported ACTION '${params.ACTION}'"
          }
          if (!(params.REQUEST_ID ==~ /\d+/)) {
            error 'REQUEST_ID must be the numeric id of an approved platform request'
          }
          if (!env.APP_HOST?.trim()) {
            error 'APP_HOST is not configured in Jenkins'
          }
          if (params.ACTION == 'rollback') {
            // Only images from our own registry with a plain tag: no shell metacharacters.
            def repo = java.util.regex.Pattern.quote(env.ECR_REPOSITORY ?: '')
            if (!env.ECR_REPOSITORY?.trim() || !(params.TARGET_IMAGE ==~ /^${repo}:[A-Za-z0-9._-]{1,128}$/)) {
              error "TARGET_IMAGE '${params.TARGET_IMAGE}' is not an image from ${env.ECR_REPOSITORY}"
            }
          }
          currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.ACTION} (request ${params.REQUEST_ID})"
          currentBuild.description = "approved by ${params.APPROVED_BY}" +
            (params.INCIDENT_ID ? " · incident #${params.INCIDENT_ID}" : '')
        }
      }
    }

    stage('Before') {
      steps {
        script { appctl('status') }
      }
    }

    stage('Execute') {
      steps {
        script {
          def rc = params.ACTION == 'rollback'
            ? appctl("rollback '${params.TARGET_IMAGE}'")
            : appctl('restart')
          if (rc != 0) {
            env.FAIL_DETAIL = "appctl ${params.ACTION} exited with code ${rc}"
            error env.FAIL_DETAIL
          }
        }
      }
    }

    stage('Post-recovery health check') {
      steps {
        script {
          def expected = params.ACTION == 'rollback' ? params.TARGET_IMAGE.tokenize(':')[-1] : ''
          def rc = sh(returnStatus: true, script: """
            python3 deploy/scripts/smoke_test.py "http://\$APP_HOST" ${expected ? "'${expected}'" : ''} \
              --timeout 90 > recovery-smoke.txt 2>&1
          """)
          sh 'cat recovery-smoke.txt'
          if (rc != 0) {
            env.FAIL_DETAIL = 'service did not pass the post-recovery health check'
            error env.FAIL_DETAIL
          }
          appctl('status')
        }
      }
    }
  }

  post {
    success {
      script { report('succeeded', "${params.ACTION} completed and health check passed") }
    }
    unsuccessful {
      script { report('failed', env.FAIL_DETAIL ?: "recovery job ${currentBuild.currentResult.toLowerCase()}") }
    }
    always {
      archiveArtifacts allowEmptyArchive: true, artifacts: 'recovery-*.txt,recovery-*.json'
    }
  }
}
