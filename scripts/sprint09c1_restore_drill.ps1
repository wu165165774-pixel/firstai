param(
    [string]$BackupId = "sprint09c1-$(Get-Date -Format 'yyyyMMddTHHmmss')"
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

try {
    Set-Location $repoRoot

    Write-Host "[1/7] Stop Worker writers"
    docker-compose `
        -f .\docker-compose.yml `
        -f .\docker-compose.worker.yml `
        stop worker
    Assert-ExternalCommand "Unable to stop Worker."
    $workerStopped = $true

    Write-Host "[2/7] Stop Backend writers"
    docker-compose stop backend
    Assert-ExternalCommand "Unable to stop Backend."
    $backendStopped = $true

    try {
        Write-Host "[3/7] Create offline backup: $BackupId"
        docker-compose run --rm --no-deps backend `
            python -m app.backup.cli create `
            --data-root /app/data `
            --output-root /app/data/backups `
            --backup-id $BackupId `
            --confirm-offline
        Assert-ExternalCommand "Backup creation failed."
    }
    finally {
        Write-Host "[4/7] Restart Backend and Worker"
        if ($backendStopped) {
            docker-compose up -d --no-deps backend
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Backend restart failed; restart it manually."
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
        }
    }

    Write-Host "[5/7] Verify backup"
    docker-compose exec -T backend `
        python -m app.backup.cli verify `
        "/app/data/backups/$BackupId"
    Assert-ExternalCommand "Backup verification failed."

    Write-Host "[6/7] Restore dry-run"
    docker-compose exec -T backend `
        python -m app.backup.cli restore `
        "/app/data/backups/$BackupId" `
        --target-root "/app/data/restore-drills/$BackupId"
    Assert-ExternalCommand "Restore dry-run failed."

    Write-Host "[7/7] Restore to a new isolated directory"
    docker-compose exec -T backend `
        python -m app.backup.cli restore `
        "/app/data/backups/$BackupId" `
        --target-root "/app/data/restore-drills/$BackupId" `
        --execute
    Assert-ExternalCommand "Restore execution failed."

    $deadline = (Get-Date).AddSeconds(30)
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
        throw "Backend health check failed after restore drill."
    }

    Write-Host "RESTORE_DRILL=OK"
    Write-Host "BACKUP_ID=$BackupId"
    Write-Host "BACKEND_STATUS=$($health.StatusCode)"
}
finally {
    Set-Location $originalLocation
}
