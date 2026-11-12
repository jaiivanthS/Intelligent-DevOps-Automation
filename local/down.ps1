<#
.SYNOPSIS
  Stop the local platform.

    powershell -ExecutionPolicy Bypass -File local\down.ps1          # stop, keep data
    powershell -ExecutionPolicy Bypass -File local\down.ps1 -Purge   # also delete volumes

  -Purge deletes Jenkins history, metrics, logs, incidents and pushed images.
  Generated .env files and the deploy key are kept either way.
#>
param([switch]$Purge)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$extra = @()
if ($Purge) { $extra = @('-v') }

# demo-app is started by appctl.sh inside app-host (compose project "app").
docker rm -f demo-app 2>$null | Out-Null

docker compose -f platform/docker-compose.yml -f local/platform.override.yml down @extra
docker compose -f jenkins/docker-compose.yml -f local/jenkins.override.yml down @extra
docker compose -f monitoring/docker-compose.yml -f local/monitoring.override.yml down @extra
docker compose -f local/docker-compose.yml down @extra
if ($Purge) {
  docker volume rm devops-app-state 2>$null | Out-Null
  docker network rm devops-net 2>$null | Out-Null
}
Write-Host 'Local platform stopped.' -ForegroundColor Green
