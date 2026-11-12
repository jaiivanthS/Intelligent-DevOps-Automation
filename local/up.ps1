<#
.SYNOPSIS
  Start the whole platform locally on Docker Desktop (no AWS needed).

.DESCRIPTION
  Starts, in order: local registry + app-host (stand-ins for ECR and the app EC2 host),
  the monitoring stack, Jenkins, and the platform website. Safe to re-run: secrets and
  .env files are only generated when missing.

    powershell -ExecutionPolicy Bypass -File local\up.ps1
    powershell -ExecutionPolicy Bypass -File local\up.ps1 -Rebuild   # rebuild images

  Stop everything with local\down.ps1.
#>
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function New-Secret([int]$Length = 24) {
  $bytes = New-Object byte[] 48
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  ([Convert]::ToBase64String($bytes) -replace '[/+=]', '').Substring(0, $Length)
}

# .env files without a BOM (docker compose would read the BOM as part of the first key).
function Write-EnvFile($Path, [string[]]$Lines) {
  [IO.File]::WriteAllText($Path, (($Lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
}

function Set-EnvValue($Path, $Key, $Value) {
  $lines = [IO.File]::ReadAllLines($Path)
  $found = $false
  $lines = foreach ($l in $lines) { if ($l -match "^$Key=") { $found = $true; "$Key=$Value" } else { $l } }
  if (-not $found) { $lines += "$Key=$Value" }
  Write-EnvFile $Path $lines
}

function Get-EnvValue($Path, $Key) {
  $m = Select-String -Path $Path -Pattern "^$Key=(.*)$" | Select-Object -First 1
  if ($m) { $m.Matches[0].Groups[1].Value } else { '' }
}

function Compose([string[]]$ComposeArgs) {
  & docker compose @ComposeArgs
  if ($LASTEXITCODE -ne 0) { Fail "docker compose $($ComposeArgs -join ' ') failed" }
}

# --- 1. Prerequisites -------------------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Fail 'Docker is not installed. Install Docker Desktop, start it, then re-run.'
}
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker Desktop is not running. Start it and wait for "Engine running".' }

$ports = @{ 3000 = 'Grafana'; 5000 = 'registry'; 8000 = 'platform-api'; 8080 = 'Jenkins'; 8081 = 'platform-ui'; 8088 = 'demo-app'; 9090 = 'Prometheus'; 9100 = 'node-exporter' }
$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $ports.ContainsKey([int]$_.LocalPort) } |
  ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -notmatch 'docker|wslrelay|vpnkit|com.docker') { "$($_.LocalPort) ($($ports[[int]$_.LocalPort])) used by $($p.ProcessName) pid $($p.Id)" } } |
  Sort-Object -Unique
if ($busy) { Fail ("These ports are taken by other programs; stop them first:`n  " + ($busy -join "`n  ")) }

docker network inspect devops-net *> $null
if ($LASTEXITCODE -ne 0) { Info 'Creating network devops-net'; docker network create devops-net | Out-Null }

# --- 2. Secrets and .env files ------------------------------------------------------------
$keyDir = Join-Path $Root 'jenkins\secrets'
New-Item -ItemType Directory -Force $keyDir | Out-Null
if (-not (Test-Path "$keyDir\app_deploy_key")) {
  Info 'Generating the Jenkins deploy key (Jenkins -> app-host)'
  & ssh-keygen -q -t ed25519 -N '""' -C 'jenkins-deploy@local' -f "$keyDir\app_deploy_key"
  if ($LASTEXITCODE -ne 0) { Fail 'ssh-keygen failed' }
}

# Group that owns the Docker socket inside containers (root on Docker Desktop).
$dockerGid = (docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine:3.20 stat -c '%g' /var/run/docker.sock).Trim()
if ($LASTEXITCODE -ne 0 -or -not $dockerGid) { Fail 'Could not read the Docker socket group id' }

$jenkinsEnv = Join-Path $Root 'jenkins\.env'
if (-not (Test-Path $jenkinsEnv)) {
  Info 'Creating jenkins\.env'
  Copy-Item (Join-Path $Root 'jenkins\.env.example') $jenkinsEnv
  Set-EnvValue $jenkinsEnv 'JENKINS_ADMIN_PASSWORD' (New-Secret)
  Set-EnvValue $jenkinsEnv 'JENKINS_URL' 'http://localhost:8080/'
  Set-EnvValue $jenkinsEnv 'ECR_REPOSITORY' 'localhost:5000/demo-app'
  Set-EnvValue $jenkinsEnv 'APP_HOST' 'app-host'
  Set-EnvValue $jenkinsEnv 'APP_URL' 'http://demo-app:8000'
  Set-EnvValue $jenkinsEnv 'PLATFORM_API_URL' 'http://platform-api:8000'
}
Set-EnvValue $jenkinsEnv 'DOCKER_GID' $dockerGid

$monEnv = Join-Path $Root 'monitoring\.env'
if (-not (Test-Path $monEnv)) {
  Info 'Creating monitoring\.env'
  Write-EnvFile $monEnv @(
    "GRAFANA_ADMIN_PASSWORD=$(New-Secret)",
    'GRAFANA_ROOT_URL=http://localhost:3000',
    'PROMETHEUS_EXTERNAL_URL=http://localhost:9090',
    'LOADGEN_RPS=2'
  )
}

$build = @('--build')
if ($Rebuild) { $build += '--pull' }

# --- 3. Registry + app-host ---------------------------------------------------------------
Info 'Starting registry and app-host'
Compose (@('-f', 'local/docker-compose.yml', 'up', '-d') + $build)

# --- 4. Monitoring --------------------------------------------------------------------------
Info 'Starting monitoring (Prometheus, Alertmanager, Loki, Promtail, Grafana, cAdvisor, loadgen)'
Compose @('-f', 'monitoring/docker-compose.yml', '-f', 'local/monitoring.override.yml', 'up', '-d')

# --- 5. Jenkins -----------------------------------------------------------------------------
Info 'Building and starting Jenkins (first build takes a few minutes)'
Compose (@('-f', 'jenkins/docker-compose.yml', '-f', 'local/jenkins.override.yml', 'up', '-d') + $build)

Info 'Waiting for Jenkins to accept logins'
$adminUser = Get-EnvValue $jenkinsEnv 'JENKINS_ADMIN_ID'
$adminPass = Get-EnvValue $jenkinsEnv 'JENKINS_ADMIN_PASSWORD'
$auth = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${adminUser}:${adminPass}"))
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    Invoke-RestMethod 'http://localhost:8080/whoAmI/api/json' -Headers @{ Authorization = $auth } -TimeoutSec 5 | Out-Null
    $ready = $true; break
  } catch { Start-Sleep -Seconds 5 }
}
if (-not $ready) { Fail 'Jenkins did not come up within 7.5 minutes. Check: docker logs jenkins' }

# --- 6. Platform ----------------------------------------------------------------------------
$platEnv = Join-Path $Root 'platform\.env'
if (-not (Test-Path $platEnv)) {
  Copy-Item (Join-Path $Root 'platform\.env.example') $platEnv
}
Set-EnvValue $platEnv 'JENKINS_URL' 'http://jenkins:8080'
Set-EnvValue $platEnv 'JENKINS_USER' $adminUser
if (-not (Get-EnvValue $platEnv 'JENKINS_TOKEN')) {
  Info 'Creating a Jenkins API token for the platform'
  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $crumb = Invoke-RestMethod 'http://localhost:8080/crumbIssuer/api/json' -Headers @{ Authorization = $auth } -WebSession $session
  $resp = Invoke-RestMethod -Method Post 'http://localhost:8080/me/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken' `
    -Headers @{ Authorization = $auth; $crumb.crumbRequestField = $crumb.crumb } `
    -Body @{ newTokenName = 'platform-local' } -WebSession $session
  if (-not $resp.data.tokenValue) { Fail 'Jenkins did not return an API token' }
  Set-EnvValue $platEnv 'JENKINS_TOKEN' $resp.data.tokenValue
}

Info 'Building and starting the platform (trains the RCA model during the build)'
Compose (@('-f', 'platform/docker-compose.yml', '-f', 'local/platform.override.yml', 'up', '-d') + $build)

# --- Done -----------------------------------------------------------------------------------
Write-Host ''
Write-Host 'Local platform is up:' -ForegroundColor Green
Write-Host '  Platform website  http://localhost:8081'
Write-Host "  Jenkins           http://localhost:8080   (user: $adminUser, password: JENKINS_ADMIN_PASSWORD in jenkins\.env)"
Write-Host '  Grafana           http://localhost:3000   (user: admin, password: GRAFANA_ADMIN_PASSWORD in monitoring\.env)'
Write-Host '  Prometheus        http://localhost:9090'
Write-Host '  Demo app          http://localhost:8088   (after the first pipeline run)'
Write-Host ''
Write-Host 'Next: in Jenkins open demo-app > Build with Parameters > Build, then approve the Approval stage.'
