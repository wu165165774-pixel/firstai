param(
    [string]$AdminToken = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$headers = @{}
if ($AdminToken) {
    $headers["Authorization"] = "Bearer $AdminToken"
}

Write-Output "[1/7] Validate Compose configurations"
docker-compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Base Compose validation failed" }
docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml config --quiet
if ($LASTEXITCODE -ne 0) { throw "Worker Compose validation failed" }

Write-Output "[2/7] Build production images"
docker-compose build backend frontend
if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend image build failed" }
docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml build worker
if ($LASTEXITCODE -ne 0) { throw "Worker image build failed" }

Write-Output "[3/7] Recreate Backend and Frontend"
docker-compose up -d --no-deps --force-recreate backend frontend
if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend recreate failed" }

Write-Output "[4/7] Recreate Worker"
docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
    up -d --no-deps --force-recreate worker
if ($LASTEXITCODE -ne 0) { throw "Worker recreate failed" }

Write-Output "[5/7] Wait for Backend and Frontend"
$backendStatus = 0
$frontendStatus = 0
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $backendStatus = (
            Invoke-WebRequest -UseBasicParsing `
                http://127.0.0.1:18080/api/v1/health
        ).StatusCode
        $frontendStatus = (
            Invoke-WebRequest -UseBasicParsing `
                http://127.0.0.1:18081/healthz
        ).StatusCode
        if ($backendStatus -eq 200 -and $frontendStatus -eq 200) { break }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}
if ($backendStatus -ne 200) { throw "Backend did not become healthy" }
if ($frontendStatus -ne 200) { throw "Frontend did not become healthy" }

Write-Output "[6/7] Verify live Plugin API contract"
$openapi = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/openapi.json
if ($openapi.info.version -ne "0.16.0-alpha.1") {
    throw "Unexpected OpenAPI version: $($openapi.info.version)"
}
if (-not $openapi.paths.PSObject.Properties["/api/v1/plugins"]) {
    throw "Plugin route is missing from OpenAPI"
}
$catalog = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/api/v1/plugins
if ($catalog.data.plugin_api_version -ne 1) { throw "Unexpected Plugin API version" }
if ($catalog.data.execution_enabled -ne $false) { throw "Plugin execution must remain disabled" }
if ($catalog.data.configuration_valid -ne $true) { throw "Plugin configuration is invalid" }
if ($catalog.data.root_available -ne $true) { throw "Read-only plugin root is unavailable" }
if ($catalog.data.plugins.Count -ne 0) { throw "Acceptance plugin root must be empty" }
$workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
    throw "Worker is not running"
}

Write-Output "[7/7] Report"
$backendImage = docker image inspect novel-ai-backend -f "{{.Id}}"
$frontendImage = docker image inspect novel-ai-frontend -f "{{.Id}}"
$workerImage = docker image inspect novel-ai-worker -f "{{.Id}}"
Write-Output "PLUGIN_DRILL=OK"
Write-Output "VERSION=$($openapi.info.version)"
Write-Output "PLUGIN_API_VERSION=$($catalog.data.plugin_api_version)"
Write-Output "PLUGIN_ROOT_AVAILABLE=$($catalog.data.root_available.ToString().ToLowerInvariant())"
Write-Output "PLUGIN_EXECUTION_ENABLED=$($catalog.data.execution_enabled.ToString().ToLowerInvariant())"
Write-Output "BACKEND_STATUS=$backendStatus"
Write-Output "FRONTEND_STATUS=$frontendStatus"
Write-Output "WORKER_RUNNING=$($workerRunning.Trim())"
Write-Output "BACKEND_IMAGE=$backendImage"
Write-Output "FRONTEND_IMAGE=$frontendImage"
Write-Output "WORKER_IMAGE=$workerImage"
