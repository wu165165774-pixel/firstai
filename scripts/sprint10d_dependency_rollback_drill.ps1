param(
    [switch]$CleanupOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$expectedVersion = "1.0.0-rc.2"
$previousVersion = "1.0.0-rc.1"
$rollbackImage = "novelforge-backend:rollback-rc1"
$probeName = "novelforge-rollback-probe"
$backupId = "sprint10d-$(Get-Date -Format 'yyyyMMddTHHmmss')"
$drillRoot = Join-Path $repoRoot "data\upgrade-drills\$backupId"
$previousPythonPath = $env:PYTHONPATH
$previousBindHost = $env:NOVELFORGE_BIND_HOST
$previousDebug = $env:DEBUG
$previousOverride = $env:ALLOW_INSECURE_NETWORK_EXPOSURE
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:NOVELFORGE_BIND_HOST = "127.0.0.1"
$env:DEBUG = "false"
$env:ALLOW_INSECURE_NETWORK_EXPOSURE = "false"

function Wait-HttpStatus {
    param(
        [string]$Uri,
        [int]$Attempts = 90
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $status = (
                Invoke-WebRequest -UseBasicParsing -Uri $Uri
            ).StatusCode
            if ($status -eq 200) { return $status }
        }
        catch {
            $status = 0
        }
        Start-Sleep -Seconds 1
    }
    throw "HTTP endpoint did not become healthy: $Uri"
}

function Restore-EnvironmentValue {
    param(
        [string]$Name,
        [object]$Value
    )
    if ($null -eq $Value) {
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    }
    else {
        Set-Item "Env:$Name" $Value
    }
}

function Invoke-DrillCleanup {
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        # docker-compose writes benign orphan warnings to stderr. Cleanup must
        # remain best-effort and must not turn those warnings into exceptions.
        $ErrorActionPreference = "SilentlyContinue"
        $probe = docker ps -a --filter "name=^/$probeName$" -q 2>$null
        if ($probe) {
            docker rm -f $probeName 2>$null | Out-Null
        }
        docker-compose up -d --no-deps backend 2>$null | Out-Null
        docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
            up -d --no-deps worker 2>$null | Out-Null
        docker image rm $rollbackImage 2>$null | Out-Null
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
}

if ($CleanupOnly) {
    try {
        Invoke-DrillCleanup
        $backendStatus = Wait-HttpStatus `
            -Uri "http://127.0.0.1:18080/api/v1/health"
        $workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
        if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
            throw "Worker is not running after cleanup"
        }
        $probe = docker ps -a --filter "name=^/$probeName$" -q
        if ($probe) { throw "Rollback probe still exists after cleanup" }
        Write-Output "SPRINT10D_CLEANUP=OK"
        Write-Output "BACKEND_STATUS=$backendStatus"
        Write-Output "WORKER_RUNNING=$($workerRunning.Trim())"
        Write-Output "ROLLBACK_PROBE_REMOVED=true"
    }
    finally {
        Restore-EnvironmentValue -Name "PYTHONPATH" -Value $previousPythonPath
        Restore-EnvironmentValue `
            -Name "NOVELFORGE_BIND_HOST" `
            -Value $previousBindHost
        Restore-EnvironmentValue -Name "DEBUG" -Value $previousDebug
        Restore-EnvironmentValue `
            -Name "ALLOW_INSECURE_NETWORK_EXPOSURE" `
            -Value $previousOverride
    }
    exit 0
}

try {
    Write-Output "[1/15] Validate dependency and compatibility contracts"
    $contract = python -c `
        "from app.release_engineering.service import ReleaseEngineeringService; import json; print(json.dumps(ReleaseEngineeringService('.').dependency_contract(), sort_keys=True))" |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Dependency contract validation failed" }
    if ($contract.backend_locked_packages -ne 34) {
        throw "Unexpected Backend lock package count"
    }
    if ($contract.frontend_locked_packages -ne 80) {
        throw "Unexpected Frontend lock package count"
    }
    if ($contract.pinned_github_actions -ne 9) {
        throw "Unexpected pinned Action count"
    }
    $upgrade = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation upgrade `
        --other-version $previousVersion `
        --schema-version 1 | ConvertFrom-Json
    $rollback = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation rollback `
        --other-version $previousVersion `
        --schema-version 1 | ConvertFrom-Json
    $newerSchema = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation rollback `
        --other-version $previousVersion `
        --schema-version 2 | ConvertFrom-Json
    $unknown = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation upgrade `
        --other-version 0.0.0 `
        --schema-version 1 | ConvertFrom-Json
    if ($upgrade.decision -ne "direct") { throw "Upgrade path is not direct" }
    if ($rollback.decision -ne "direct") { throw "Rollback path is not direct" }
    if ($newerSchema.decision -ne "restore_backup") {
        throw "Newer-schema rollback did not require backup restore"
    }
    if ($unknown.decision -ne "blocked") {
        throw "Unknown compatibility path did not fail closed"
    }

    Write-Output "[2/15] Validate Compose configurations"
    docker-compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Base Compose validation failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Worker Compose validation failed" }

    Write-Output "[3/15] Run Frontend tests"
    npm test --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }

    Write-Output "[4/15] Preserve the accepted RC1 Backend image"
    $oldVersion = docker run --rm --entrypoint python novel-ai-backend `
        -c "from app.version import APP_VERSION; print(APP_VERSION)"
    if ($LASTEXITCODE -ne 0 -or $oldVersion.Trim() -ne $previousVersion) {
        throw "Local Backend image is not the accepted $previousVersion image"
    }
    docker tag novel-ai-backend $rollbackImage
    if ($LASTEXITCODE -ne 0) { throw "Could not preserve the RC1 image" }

    Write-Output "[5/15] Stop writers and create an offline backup"
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        stop worker
    if ($LASTEXITCODE -ne 0) { throw "Could not stop Worker" }
    docker-compose stop backend
    if ($LASTEXITCODE -ne 0) { throw "Could not stop Backend" }
    docker-compose run --rm --no-deps backend `
        python -m app.backup.cli create `
        --data-root /app/data `
        --output-root /app/data/backups `
        --backup-id $backupId `
        --confirm-offline
    if ($LASTEXITCODE -ne 0) { throw "Offline backup failed" }

    Write-Output "[6/15] Restore the backup to an isolated rollback root"
    docker-compose run --rm --no-deps backend `
        python -m app.backup.cli restore `
        "/app/data/backups/$backupId" `
        --target-root "/app/data/upgrade-drills/$backupId" `
        --execute
    if ($LASTEXITCODE -ne 0) { throw "Isolated restore failed" }
    if (-not (Test-Path -LiteralPath $drillRoot -PathType Container)) {
        throw "Isolated restore root is missing"
    }

    Write-Output "[7/15] Build digest-pinned RC2 production images"
    docker-compose build backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend build failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        build worker
    if ($LASTEXITCODE -ne 0) { throw "Worker build failed" }

    Write-Output "[8/15] Verify installed Python runtime matches the lock"
    docker run --rm --entrypoint python novel-ai-backend `
        -m app.release_engineering.runtime_lock `
        --lock /app/requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "Backend runtime lock verification failed" }
    docker run --rm --entrypoint python novel-ai-worker `
        -m app.release_engineering.runtime_lock `
        --lock /app/requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "Worker runtime lock verification failed" }

    Write-Output "[9/15] Start RC2 production services"
    docker-compose up -d --no-deps --force-recreate ollama backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Base service recreate failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        up -d --no-deps --force-recreate worker
    if ($LASTEXITCODE -ne 0) { throw "Worker recreate failed" }

    Write-Output "[10/15] Verify RC2 live version and schema"
    $backendStatus = Wait-HttpStatus `
        -Uri "http://127.0.0.1:18080/api/v1/health"
    $frontendStatus = Wait-HttpStatus `
        -Uri "http://127.0.0.1:18081/healthz"
    $openapi = Invoke-RestMethod http://127.0.0.1:18080/openapi.json
    if ($openapi.info.version -ne $expectedVersion) {
        throw "Unexpected live version: $($openapi.info.version)"
    }
    $schema = docker exec novelforge-backend `
        python -m app.schema_migrations.cli verify `
        --data-root /app/data | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $schema.ready -ne $true) {
        throw "Live schema v1 verification failed"
    }

    Write-Output "[11/15] Run focused Backend regressions"
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests `
        -p "test_release_engineering.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Release Engineering tests failed" }
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests `
        -p "test_dependency_lock.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Dependency lock tests failed" }
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests `
        -p "test_schema_migrations.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Schema Migration tests failed" }

    Write-Output "[12/15] Run full Backend regression"
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Backend full regression failed" }

    Write-Output "[13/15] Boot RC1 against the isolated schema-v1 restore"
    $existingProbe = docker ps -a --filter "name=^/$probeName$" -q
    if ($existingProbe) {
        throw "Rollback probe container already exists"
    }
    docker run -d `
        --name $probeName `
        --network novel-ai_default `
        -p 127.0.0.1:18082:8000 `
        --mount "type=bind,source=$drillRoot,target=/app/data" `
        --mount "type=bind,source=$repoRoot\plugins,target=/app/plugins,readonly" `
        -e NOVELFORGE_BIND_HOST=127.0.0.1 `
        -e DEBUG=false `
        -e ALLOW_INSECURE_NETWORK_EXPOSURE=false `
        -e QWEN_BASE_URL=http://ollama:11434 `
        -e OLLAMA_BASE_URL=http://ollama:11434 `
        -e PLUGIN_ROOT=/app/plugins `
        -e PLUGIN_ENABLED_JSON=[] `
        -e PLUGIN_EXECUTION_ENABLED=false `
        $rollbackImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not start rollback probe" }
    $rollbackStatus = Wait-HttpStatus `
        -Uri "http://127.0.0.1:18082/api/v1/health"
    $rollbackOpenapi = Invoke-RestMethod http://127.0.0.1:18082/openapi.json
    if ($rollbackOpenapi.info.version -ne $previousVersion) {
        throw "Rollback probe did not boot the RC1 image"
    }
    $rollbackSchema = docker exec $probeName `
        python -m app.schema_migrations.cli verify `
        --data-root /app/data | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $rollbackSchema.ready -ne $true) {
        throw "RC1 could not verify the isolated schema-v1 restore"
    }
    docker rm -f $probeName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not remove rollback probe" }

    Write-Output "[14/15] Verify RC2 remains healthy after rollback probe"
    $backendStatus = Wait-HttpStatus `
        -Uri "http://127.0.0.1:18080/api/v1/health"
    $frontendStatus = Wait-HttpStatus `
        -Uri "http://127.0.0.1:18081/healthz"
    $workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
    if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
        throw "Worker is not running"
    }
    $ollamaDigests = docker image inspect `
        "ollama/ollama@sha256:6345fbc18bd73a1e16404be681dbc6fd291a027cab43ed541abe78c4c81051b0" `
        --format "{{json .RepoDigests}}"
    if (
        $LASTEXITCODE -ne 0 -or
        $ollamaDigests -notmatch "6345fbc18bd73a1e16404be681dbc6fd291a027cab43ed541abe78c4c81051b0"
    ) {
        throw "Ollama digest verification failed"
    }

    Write-Output "[15/15] Report"
    $backendImage = docker image inspect novel-ai-backend -f "{{.Id}}"
    $frontendImage = docker image inspect novel-ai-frontend -f "{{.Id}}"
    $workerImage = docker image inspect novel-ai-worker -f "{{.Id}}"
    Write-Output "DEPENDENCY_ROLLBACK_DRILL=OK"
    Write-Output "VERSION=$expectedVersion"
    Write-Output "BACKEND_LOCKED_PACKAGES=$($contract.backend_locked_packages)"
    Write-Output "FRONTEND_LOCKED_PACKAGES=$($contract.frontend_locked_packages)"
    Write-Output "PINNED_IMAGES=4"
    Write-Output "PINNED_GITHUB_ACTIONS=$($contract.pinned_github_actions)"
    Write-Output "FRONTEND_TESTS=passed"
    Write-Output "BACKEND_FOCUSED_TESTS=passed"
    Write-Output "BACKEND_FULL_REGRESSION=passed"
    Write-Output "UPGRADE_RC1_TO_RC2=direct"
    Write-Output "ROLLBACK_RC2_TO_RC1=direct"
    Write-Output "NEWER_SCHEMA_ROLLBACK=restore_backup"
    Write-Output "UNKNOWN_PATH=blocked"
    Write-Output "ROLLBACK_PROBE_VERSION=$($rollbackOpenapi.info.version)"
    Write-Output "SCHEMA_VERSION=$($schema.target_version)"
    Write-Output "BACKUP_ID=$backupId"
    Write-Output "BACKEND_STATUS=$backendStatus"
    Write-Output "FRONTEND_STATUS=$frontendStatus"
    Write-Output "ROLLBACK_STATUS=$rollbackStatus"
    Write-Output "WORKER_RUNNING=$($workerRunning.Trim())"
    Write-Output "BACKEND_IMAGE=$backendImage"
    Write-Output "FRONTEND_IMAGE=$frontendImage"
    Write-Output "WORKER_IMAGE=$workerImage"
}
finally {
    Invoke-DrillCleanup
    Restore-EnvironmentValue -Name "PYTHONPATH" -Value $previousPythonPath
    Restore-EnvironmentValue -Name "NOVELFORGE_BIND_HOST" -Value $previousBindHost
    Restore-EnvironmentValue -Name "DEBUG" -Value $previousDebug
    Restore-EnvironmentValue `
        -Name "ALLOW_INSECURE_NETWORK_EXPOSURE" `
        -Value $previousOverride
}
