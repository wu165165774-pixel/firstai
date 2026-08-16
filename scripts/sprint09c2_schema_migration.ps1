param(
    [string]$BackupId = "sprint09c2-$(Get-Date -Format 'yyyyMMddTHHmmss')"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExternalCommand {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

$originalLocation = (Get-Location).Path
$repoRoot = Split-Path -Parent $PSScriptRoot
$workerStopped = $false
$backendStopped = $false
$backupPath = "/app/data/backups/$BackupId"
$rehearsalRoot = "/app/data/migration-drills/$BackupId"

try {
    Set-Location $repoRoot

    Write-Host "[1/12] Inspect production schema before maintenance"
    docker-compose exec -T backend `
        python -m app.schema_migrations.cli status `
        --data-root /app/data
    Assert-ExternalCommand "Pre-maintenance schema status failed."

    Write-Host "[2/12] Stop Worker writers"
    docker-compose `
        -f .\docker-compose.yml `
        -f .\docker-compose.worker.yml `
        stop worker
    Assert-ExternalCommand "Unable to stop Worker."
    $workerStopped = $true

    Write-Host "[3/12] Stop Backend writers"
    docker-compose stop backend
    Assert-ExternalCommand "Unable to stop Backend."
    $backendStopped = $true

    try {
        Write-Host "[4/12] Create verified offline backup: $BackupId"
        docker-compose run --rm --no-deps backend `
            python -m app.backup.cli create `
            --data-root /app/data `
            --output-root /app/data/backups `
            --backup-id $BackupId `
            --confirm-offline
        Assert-ExternalCommand "Migration backup creation failed."

        Write-Host "[5/12] Restore backup to isolated rehearsal root"
        docker-compose run --rm --no-deps backend `
            python -m app.backup.cli restore $backupPath `
            --target-root $rehearsalRoot `
            --execute
        Assert-ExternalCommand "Migration rehearsal restore failed."

        Write-Host "[6/12] Upgrade isolated rehearsal copy"
        docker-compose run --rm --no-deps backend `
            python -m app.schema_migrations.cli upgrade `
            --data-root $rehearsalRoot `
            --backup-dir $backupPath `
            --confirm-offline
        Assert-ExternalCommand "Isolated schema migration failed."

        Write-Host "[7/12] Verify isolated rehearsal copy"
        docker-compose run --rm --no-deps backend `
            python -m app.schema_migrations.cli verify `
            --data-root $rehearsalRoot
        Assert-ExternalCommand "Isolated schema verification failed."

        Write-Host "[8/12] Upgrade production authorities"
        docker-compose run --rm --no-deps backend `
            python -m app.schema_migrations.cli upgrade `
            --data-root /app/data `
            --backup-dir $backupPath `
            --confirm-offline
        Assert-ExternalCommand "Production schema migration failed."

        Write-Host "[9/12] Verify production authorities"
        docker-compose run --rm --no-deps backend `
            python -m app.schema_migrations.cli verify `
            --data-root /app/data
        Assert-ExternalCommand "Production schema verification failed."
    }
    finally {
        Write-Host "[10/12] Restart Backend and Worker"
        if ($backendStopped) {
            docker-compose up -d --no-deps backend
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Backend restart failed; restart it manually."
            }
            else {
                $backendStopped = $false
            }
        }
        if ($workerStopped) {
            docker-compose `
                -f .\docker-compose.yml `
                -f .\docker-compose.worker.yml `
                up -d --no-deps worker
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Worker restart failed; restart it manually."
            }
            else {
                $workerStopped = $false
            }
        }
    }

    Write-Host "[11/12] Wait for Backend schema-compatible startup"
    $deadline = (Get-Date).AddSeconds(45)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-WebRequest `
                -UseBasicParsing `
                http://127.0.0.1:18080/api/v1/health `
                -TimeoutSec 3
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if ($null -eq $health -or $health.StatusCode -ne 200) {
        throw "Backend health check failed after schema migration."
    }

    Write-Host "[12/12] Verify live v1 schema"
    docker-compose exec -T backend `
        python -m app.schema_migrations.cli verify `
        --data-root /app/data
    Assert-ExternalCommand "Live schema verification failed."

    Write-Host "SCHEMA_MIGRATION=OK"
    Write-Host "BACKUP_ID=$BackupId"
    Write-Host "SCHEMA_VERSION=1"
    Write-Host "BACKEND_STATUS=$($health.StatusCode)"
}
finally {
    Set-Location $repoRoot
    if ($backendStopped) {
        docker-compose up -d --no-deps backend
    }
    if ($workerStopped) {
        docker-compose `
            -f .\docker-compose.yml `
            -f .\docker-compose.worker.yml `
            up -d --no-deps worker
    }
    Set-Location $originalLocation
}
