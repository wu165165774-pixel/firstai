param(
    [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $ExpectedVersion) {
    $line = Get-Content .\backend\app\version.py -Raw
    $match = [regex]::Match($line, 'APP_VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) { throw "Could not read APP_VERSION" }
    $ExpectedVersion = $match.Groups[1].Value
}

$outputDir = Join-Path $repoRoot "dist\release-drill"
$artifact = Join-Path $outputDir "novelforge-v$ExpectedVersion-source.zip"
$env:PYTHONPATH = (Resolve-Path .\backend).Path

Write-Output "[1/7] Validate release identity and acceptance"
python -m app.release_engineering.cli validate `
    --repo-root $repoRoot `
    --expected-version $ExpectedVersion
if ($LASTEXITCODE -ne 0) { throw "Release validation failed" }

Write-Output "[2/7] Evaluate local Go/No-Go evidence"
python -m app.release_engineering.cli go-no-go `
    --repo-root $repoRoot `
    --expected-version $ExpectedVersion
if ($LASTEXITCODE -ne 0) { throw "Local Go/No-Go validation failed" }

Write-Output "[3/7] Validate Compose portability"
docker-compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Base Compose validation failed" }
docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml config --quiet
if ($LASTEXITCODE -ne 0) { throw "Worker Compose validation failed" }

Write-Output "[4/7] Build deterministic source artifact"
python -m app.release_engineering.cli package `
    --repo-root $repoRoot `
    --output-dir $outputDir `
    --expected-version $ExpectedVersion
if ($LASTEXITCODE -ne 0) { throw "Release package failed" }

Write-Output "[5/7] Verify artifact independently"
python -m app.release_engineering.cli verify $artifact
if ($LASTEXITCODE -ne 0) { throw "Release artifact verification failed" }

Write-Output "[6/7] Rebuild and compare deterministic artifact"
$firstHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
python -m app.release_engineering.cli package `
    --repo-root $repoRoot `
    --output-dir $outputDir `
    --expected-version $ExpectedVersion | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Repeat release package failed" }
$secondHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
if ($firstHash -ne $secondHash) { throw "Source artifact is not deterministic" }

Write-Output "[7/7] Report"
Write-Output "RELEASE_DRILL=OK"
Write-Output "VERSION=$ExpectedVersion"
Write-Output "ARTIFACT=$artifact"
Write-Output "SHA256=$secondHash"
Write-Output "DETERMINISTIC=true"
