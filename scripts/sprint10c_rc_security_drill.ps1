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

$previousBindHost = $env:NOVELFORGE_BIND_HOST
$previousDebug = $env:DEBUG
$previousOverride = $env:ALLOW_INSECURE_NETWORK_EXPOSURE
$env:NOVELFORGE_BIND_HOST = "127.0.0.1"
$env:DEBUG = "false"
$env:ALLOW_INSECURE_NETWORK_EXPOSURE = "false"

function Assert-SecurityHeaders {
    param([object]$Response)

    if ($Response.Headers["X-Content-Type-Options"] -ne "nosniff") {
        throw "X-Content-Type-Options header is missing"
    }
    if ($Response.Headers["X-Frame-Options"] -ne "DENY") {
        throw "X-Frame-Options header is missing"
    }
    if ($Response.Headers["Referrer-Policy"] -ne "no-referrer") {
        throw "Referrer-Policy header is missing"
    }
    if (
        $Response.Headers["Content-Security-Policy"] -notmatch
        "default-src 'self'"
    ) {
        throw "Content-Security-Policy header is missing"
    }
}

try {
    Write-Output "[1/10] Validate Compose configurations"
    docker-compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Base Compose validation failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Worker Compose validation failed" }

    Write-Output "[2/10] Verify unsafe non-loopback exposure fails closed"
    try {
        $ErrorActionPreference = "Continue"
        $unsafeOutput = docker-compose run --rm --no-deps backend `
            python -c "from app.core.deployment_security import validate_deployment_security; validate_deployment_security(bind_host='0.0.0.0', auth_enabled=False, debug_enabled=False, allow_insecure_network_exposure=False)" `
            2>&1
        $unsafeExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = "Stop"
    }
    if ($unsafeExit -eq 0) { throw "Unsafe exposure unexpectedly passed" }
    if (($unsafeOutput -join "`n") -notmatch "unsafe_network_exposure") {
        throw "Unsafe exposure did not return its stable error code"
    }

    Write-Output "[3/10] Verify authenticated production exposure is admissible"
    docker-compose run --rm --no-deps backend `
        python -c "from app.core.deployment_security import validate_deployment_security; validate_deployment_security(bind_host='192.168.10.20', auth_enabled=True, debug_enabled=False, allow_insecure_network_exposure=False)"
    if ($LASTEXITCODE -ne 0) { throw "Authenticated exposure validation failed" }

    Write-Output "[4/10] Build production images"
    docker-compose build backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend image build failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml build worker
    if ($LASTEXITCODE -ne 0) { throw "Worker image build failed" }

    Write-Output "[5/10] Recreate loopback-only production services"
    docker-compose up -d --no-deps --force-recreate ollama backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Base service recreate failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        up -d --no-deps --force-recreate worker
    if ($LASTEXITCODE -ne 0) { throw "Worker recreate failed" }

    Write-Output "[6/10] Wait for Backend, Frontend and Ollama"
    $backendStatus = 0
    $frontendStatus = 0
    $ollamaStatus = 0
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        try {
            $backendStatus = (
                Invoke-WebRequest -UseBasicParsing `
                    http://127.0.0.1:18080/api/v1/health
            ).StatusCode
            $frontendStatus = (
                Invoke-WebRequest -UseBasicParsing `
                    http://127.0.0.1:18081/healthz
            ).StatusCode
            $ollamaStatus = (
                Invoke-WebRequest -UseBasicParsing `
                    http://127.0.0.1:11434/api/tags
            ).StatusCode
        }
        catch {
            $backendStatus = 0
            $frontendStatus = 0
            $ollamaStatus = 0
        }
        if (
            $backendStatus -eq 200 -and
            $frontendStatus -eq 200 -and
            $ollamaStatus -eq 200
        ) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if ($backendStatus -ne 200) { throw "Backend did not become healthy" }
    if ($frontendStatus -ne 200) { throw "Frontend did not become healthy" }
    if ($ollamaStatus -ne 200) { throw "Ollama did not become healthy" }

    Write-Output "[7/10] Verify actual Docker host bindings"
    $backendPort = (docker port novelforge-backend 8000/tcp).Trim()
    $frontendPort = (docker port novelforge-frontend 80/tcp).Trim()
    $ollamaPort = (docker port novelforge-ollama 11434/tcp).Trim()
    if ($backendPort -ne "127.0.0.1:18080") { throw "Backend is not loopback-only" }
    if ($frontendPort -ne "127.0.0.1:18081") { throw "Frontend is not loopback-only" }
    if ($ollamaPort -ne "127.0.0.1:11434") { throw "Ollama is not loopback-only" }

    Write-Output "[8/10] Verify live version, runtime flags and security headers"
    $runtimeFlags = docker exec novelforge-backend python -c `
        "from app.config.settings import settings; print(f'{settings.novelforge_bind_host}|{str(settings.debug).lower()}|{str(settings.allow_insecure_network_exposure).lower()}')"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect Backend runtime flags" }
    if ($runtimeFlags.Trim() -ne "127.0.0.1|false|false") {
        throw "Backend runtime flags are not production-safe"
    }
    $openapi = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/openapi.json
    if ($openapi.info.version -ne "1.0.0-rc.1") {
        throw "Unexpected OpenAPI version: $($openapi.info.version)"
    }
    $catalog = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/api/v1/plugins
    if ($catalog.data.execution_enabled -ne $false) {
        throw "Plugin execution must be disabled by default"
    }
    $frontend = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18081/
    $proxiedApi = Invoke-WebRequest -UseBasicParsing `
        http://127.0.0.1:18081/api/v1/health
    Assert-SecurityHeaders $frontend
    Assert-SecurityHeaders $proxiedApi

    Write-Output "[9/10] Verify Worker remains healthy"
    $workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
    if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
        throw "Worker is not running"
    }

    Write-Output "[10/10] Report"
    $backendImage = docker image inspect novel-ai-backend -f "{{.Id}}"
    $frontendImage = docker image inspect novel-ai-frontend -f "{{.Id}}"
    $workerImage = docker image inspect novel-ai-worker -f "{{.Id}}"
    Write-Output "RC_SECURITY_DRILL=OK"
    Write-Output "VERSION=$($openapi.info.version)"
    Write-Output "UNSAFE_EXPOSURE_BLOCKED=true"
    Write-Output "AUTHENTICATED_EXPOSURE_ALLOWED=true"
    Write-Output "BACKEND_BINDING=$backendPort"
    Write-Output "FRONTEND_BINDING=$frontendPort"
    Write-Output "OLLAMA_BINDING=$ollamaPort"
    Write-Output "DEBUG_ENABLED=false"
    Write-Output "INSECURE_OVERRIDE=false"
    Write-Output "SECURITY_HEADERS=true"
    Write-Output "PLUGIN_EXECUTION_ENABLED=false"
    Write-Output "BACKEND_STATUS=$backendStatus"
    Write-Output "FRONTEND_STATUS=$frontendStatus"
    Write-Output "OLLAMA_STATUS=$ollamaStatus"
    Write-Output "WORKER_RUNNING=$($workerRunning.Trim())"
    Write-Output "BACKEND_IMAGE=$backendImage"
    Write-Output "FRONTEND_IMAGE=$frontendImage"
    Write-Output "WORKER_IMAGE=$workerImage"
}
finally {
    if ($null -eq $previousBindHost) {
        Remove-Item Env:NOVELFORGE_BIND_HOST -ErrorAction SilentlyContinue
    }
    else {
        $env:NOVELFORGE_BIND_HOST = $previousBindHost
    }
    if ($null -eq $previousDebug) {
        Remove-Item Env:DEBUG -ErrorAction SilentlyContinue
    }
    else {
        $env:DEBUG = $previousDebug
    }
    if ($null -eq $previousOverride) {
        Remove-Item Env:ALLOW_INSECURE_NETWORK_EXPOSURE -ErrorAction SilentlyContinue
    }
    else {
        $env:ALLOW_INSECURE_NETWORK_EXPOSURE = $previousOverride
    }
}
