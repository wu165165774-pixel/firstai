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

$pluginRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "plugins"))
$fixturePath = [System.IO.Path]::GetFullPath(
    (Join-Path $pluginRoot "sprint10b-runtime-fixture")
)
$expectedPrefix = $pluginRoot.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
if (-not $fixturePath.StartsWith(
    $expectedPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Fixture path escaped the plugin root"
}
if (-not (Test-Path -LiteralPath $pluginRoot -PathType Container)) {
    throw "Plugin root does not exist: $pluginRoot"
}
$installedPlugins = @(
    Get-ChildItem -LiteralPath $pluginRoot -Force |
        Where-Object { $_.Name -ne ".gitkeep" }
)
if ($installedPlugins.Count -ne 0) {
    throw "Sprint 10B drill requires an otherwise empty plugin root"
}

$previousEnabled = $env:PLUGIN_ENABLED_JSON
$previousExecution = $env:PLUGIN_EXECUTION_ENABLED
$previousGrants = $env:PLUGIN_PERMISSION_GRANTS_JSON
$fixtureCreated = $false
$drillPassed = $false
$servicesMayHaveChanged = $false
$entryHash = ""
$backendStatus = 0
$frontendStatus = 0
$workerRunning = "false"
$marker = "/tmp/novelforge-sprint10b-plugin-active"

try {
    Write-Output "[1/10] Create an integrity-pinned local fixture"
    New-Item -ItemType Directory -Path $fixturePath | Out-Null
    $fixtureCreated = $true
    $source = @'
from pathlib import Path

MARKER = Path("/tmp/novelforge-sprint10b-plugin-active")


class Handle:
    def deactivate(self):
        MARKER.unlink(missing_ok=True)


def activate(context):
    context.register_extension(
        "prompt",
        "sprint10b.fixture.prompt",
        {"status": "active"},
    )
    MARKER.write_text(
        f"{context.plugin_id}:{context.core_version}",
        encoding="utf-8",
    )
    return Handle()
'@
    $entryPath = Join-Path $fixturePath "plugin.py"
    [System.IO.File]::WriteAllText(
        $entryPath,
        $source,
        [System.Text.UTF8Encoding]::new($false)
    )
    $entryHash = (Get-FileHash -LiteralPath $entryPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        manifest_version = 2
        plugin_id = "sprint10b.fixture"
        name = "Sprint 10B Runtime Fixture"
        version = "1.0.0"
        description = "Ephemeral production drill fixture"
        entry_point = "plugin:activate"
        capabilities = @("prompt")
        permissions = @("filesystem_write")
        requires = [ordered]@{
            plugin_api = 1
            min_core_version = "0.16.0-alpha.2"
            max_core_version_exclusive = "1.0.0"
        }
        integrity = [ordered]@{
            entry_point_sha256 = $entryHash
        }
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $fixturePath "novelforge-plugin.json"),
        ($manifest | ConvertTo-Json -Depth 6),
        [System.Text.UTF8Encoding]::new($false)
    )

    $env:PLUGIN_ENABLED_JSON = '["sprint10b.fixture"]'
    $env:PLUGIN_EXECUTION_ENABLED = "true"
    $env:PLUGIN_PERMISSION_GRANTS_JSON = '{"sprint10b.fixture":["filesystem_write"]}'

    Write-Output "[2/10] Validate Compose configurations"
    docker-compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Base Compose validation failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Worker Compose validation failed" }

    Write-Output "[3/10] Build production images"
    docker-compose build backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend image build failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml build worker
    if ($LASTEXITCODE -ne 0) { throw "Worker image build failed" }

    Write-Output "[4/10] Recreate Backend and Frontend with execution enabled"
    $servicesMayHaveChanged = $true
    docker-compose up -d --no-deps --force-recreate backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend recreate failed" }

    Write-Output "[5/10] Recreate Worker with execution enabled"
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        up -d --no-deps --force-recreate worker
    if ($LASTEXITCODE -ne 0) { throw "Worker recreate failed" }

    Write-Output "[6/10] Wait for services and both activation markers"
    $backendMarker = $false
    $workerMarker = $false
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
        }
        catch {
            $backendStatus = 0
            $frontendStatus = 0
        }
        docker exec novelforge-backend test -f $marker 2>$null
        $backendMarker = $LASTEXITCODE -eq 0
        docker exec novelforge-worker test -f $marker 2>$null
        $workerMarker = $LASTEXITCODE -eq 0
        if (
            $backendStatus -eq 200 -and
            $frontendStatus -eq 200 -and
            $backendMarker -and
            $workerMarker
        ) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if ($backendStatus -ne 200) { throw "Backend did not become healthy" }
    if ($frontendStatus -ne 200) { throw "Frontend did not become healthy" }
    if (-not $backendMarker) { throw "Backend plugin activation marker is missing" }
    if (-not $workerMarker) { throw "Worker plugin activation marker is missing" }

    Write-Output "[7/10] Verify live runtime Catalog"
    $openapi = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/openapi.json
    if ($openapi.info.version -ne "0.16.0-alpha.2") {
        throw "Unexpected OpenAPI version: $($openapi.info.version)"
    }
    $catalog = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/api/v1/plugins
    if ($catalog.data.execution_enabled -ne $true) { throw "Plugin execution is not enabled" }
    if ($catalog.data.configuration_valid -ne $true) { throw "Plugin configuration is invalid" }
    $activePlugins = @($catalog.data.active_plugins)
    if ($activePlugins.Count -ne 1) { throw "Unexpected active plugin count" }
    if ($activePlugins[0] -ne "sprint10b.fixture") {
        throw "Unexpected active plugin"
    }
    $catalogPlugin = @($catalog.data.plugins) | Where-Object {
        $_.plugin_id -eq "sprint10b.fixture"
    }
    if ($null -eq $catalogPlugin) { throw "Fixture is missing from Catalog" }
    if ($catalogPlugin.manifest_version -ne 2) { throw "Fixture is not Manifest v2" }
    if ($catalogPlugin.loaded -ne $true) { throw "Fixture is not loaded in Backend" }
    if ($catalogPlugin.manifest_sha256.Length -ne 64) { throw "Manifest digest is missing" }

    Write-Output "[8/10] Verify Worker process remains healthy"
    $workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
    if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
        throw "Worker is not running"
    }
    $drillPassed = $true
}
finally {
    try {
        if ($servicesMayHaveChanged) {
            Write-Output "[9/10] Restore default-disabled runtime"
            $env:PLUGIN_ENABLED_JSON = "[]"
            $env:PLUGIN_EXECUTION_ENABLED = "false"
            $env:PLUGIN_PERMISSION_GRANTS_JSON = "{}"
            docker-compose up -d --no-deps --force-recreate backend
            if ($LASTEXITCODE -ne 0) { throw "Backend default restore failed" }
            docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
                up -d --no-deps --force-recreate worker
            if ($LASTEXITCODE -ne 0) { throw "Worker default restore failed" }
        }
        else {
            Write-Output "[9/10] Services unchanged; default restore not required"
        }
    }
    finally {
        Write-Output "[10/10] Remove the exact temporary fixture"
        if ($fixtureCreated -and (Test-Path -LiteralPath $fixturePath)) {
            Remove-Item -LiteralPath $fixturePath -Recurse -Force
        }
        if ($null -eq $previousEnabled) {
            Remove-Item Env:PLUGIN_ENABLED_JSON -ErrorAction SilentlyContinue
        }
        else {
            $env:PLUGIN_ENABLED_JSON = $previousEnabled
        }
        if ($null -eq $previousExecution) {
            Remove-Item Env:PLUGIN_EXECUTION_ENABLED -ErrorAction SilentlyContinue
        }
        else {
            $env:PLUGIN_EXECUTION_ENABLED = $previousExecution
        }
        if ($null -eq $previousGrants) {
            Remove-Item Env:PLUGIN_PERMISSION_GRANTS_JSON -ErrorAction SilentlyContinue
        }
        else {
            $env:PLUGIN_PERMISSION_GRANTS_JSON = $previousGrants
        }
    }
}

if (-not $drillPassed) { throw "Sprint 10B runtime drill did not complete" }

$restoredStatus = 0
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $restoredStatus = (
            Invoke-WebRequest -UseBasicParsing `
                http://127.0.0.1:18080/api/v1/health
        ).StatusCode
        if ($restoredStatus -eq 200) { break }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}
if ($restoredStatus -ne 200) { throw "Restored Backend did not become healthy" }
$restoredCatalog = Invoke-RestMethod -Headers $headers http://127.0.0.1:18080/api/v1/plugins
if ($restoredCatalog.data.execution_enabled -ne $false) {
    throw "Plugin execution was not restored to disabled"
}
if (@($restoredCatalog.data.active_plugins).Count -ne 0) {
    throw "Plugins remain active after default restore"
}
if (@($restoredCatalog.data.plugins).Count -ne 0) {
    throw "Temporary fixture remains visible after cleanup"
}
$workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
    throw "Restored Worker is not running"
}

$backendImage = docker image inspect novel-ai-backend -f "{{.Id}}"
$frontendImage = docker image inspect novel-ai-frontend -f "{{.Id}}"
$workerImage = docker image inspect novel-ai-worker -f "{{.Id}}"
Write-Output "PLUGIN_RUNTIME_DRILL=OK"
Write-Output "VERSION=$($openapi.info.version)"
Write-Output "PLUGIN_API_VERSION=$($catalog.data.plugin_api_version)"
Write-Output "MANIFEST_VERSION=$($catalogPlugin.manifest_version)"
Write-Output "ENTRY_POINT_SHA256=$entryHash"
Write-Output "BACKEND_PLUGIN_LOADED=$($catalogPlugin.loaded.ToString().ToLowerInvariant())"
Write-Output "WORKER_PLUGIN_MARKER=true"
Write-Output "ROLLBACK_TO_DISABLED=true"
Write-Output "BACKEND_STATUS=$restoredStatus"
Write-Output "FRONTEND_STATUS=$frontendStatus"
Write-Output "WORKER_RUNNING=$($workerRunning.Trim())"
Write-Output "BACKEND_IMAGE=$backendImage"
Write-Output "FRONTEND_IMAGE=$frontendImage"
Write-Output "WORKER_IMAGE=$workerImage"
