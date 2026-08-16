param(
    [string]$NovelId = "",
    [string]$AccessToken = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$tempRoot = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
).TrimEnd([char[]]"\/")
$runId = [guid]::NewGuid().ToString("N")
$archiveOne = Join-Path $tempRoot "novelforge-export-$runId-1.zip"
$archiveTwo = Join-Path $tempRoot "novelforge-export-$runId-2.zip"

function Get-Sha256Bytes([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Download-Archive([string]$Uri, [string]$Target) {
    $request = [System.Net.HttpWebRequest]::Create($Uri)
    $request.Method = "GET"
    $request.Timeout = 120000
    if ($AccessToken) {
        $request.Headers["Authorization"] = "Bearer $AccessToken"
    }
    $response = $request.GetResponse()
    try {
        $stream = $response.GetResponseStream()
        $file = [System.IO.File]::Create($Target)
        try {
            $stream.CopyTo($file)
        }
        finally {
            $file.Dispose()
            $stream.Dispose()
        }
        return @{
            StatusCode = [int]$response.StatusCode
            ManifestSha256 = $response.Headers["X-NovelForge-Manifest-SHA256"]
            AcceptedChapters = [int]$response.Headers["X-NovelForge-Accepted-Chapters"]
        }
    }
    finally {
        $response.Dispose()
    }
}

function Verify-Archive([string]$Path, [string]$ExpectedNovelId, [string]$ExpectedManifestHash) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $entries = @{}
        foreach ($entry in $archive.Entries) {
            if ($entries.ContainsKey($entry.FullName)) {
                throw "Duplicate ZIP member: $($entry.FullName)"
            }
            $entries[$entry.FullName] = $entry
        }
        if (-not $entries.ContainsKey("manifest.json")) {
            throw "manifest.json is missing"
        }
        $manifestStream = $entries["manifest.json"].Open()
        $memory = New-Object System.IO.MemoryStream
        try {
            $manifestStream.CopyTo($memory)
            $manifestBytes = $memory.ToArray()
        }
        finally {
            $memory.Dispose()
            $manifestStream.Dispose()
        }
        $manifestHash = Get-Sha256Bytes $manifestBytes
        if ($manifestHash -ne $ExpectedManifestHash) {
            throw "Manifest response hash mismatch"
        }
        $manifest = [System.Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json
        if ($manifest.format -ne "novelforge-novel-export" -or [int]$manifest.format_version -ne 1) {
            throw "Unsupported export manifest"
        }
        if ($manifest.novel.novel_id -ne $ExpectedNovelId) {
            throw "Manifest novel scope mismatch"
        }
        foreach ($item in @($manifest.files)) {
            if (-not $entries.ContainsKey([string]$item.path)) {
                throw "Manifest member is missing: $($item.path)"
            }
            $entry = $entries[[string]$item.path]
            if ([long]$entry.Length -ne [long]$item.bytes) {
                throw "Member length mismatch: $($item.path)"
            }
            $entryStream = $entry.Open()
            $entryMemory = New-Object System.IO.MemoryStream
            try {
                $entryStream.CopyTo($entryMemory)
                $actualHash = Get-Sha256Bytes $entryMemory.ToArray()
            }
            finally {
                $entryMemory.Dispose()
                $entryStream.Dispose()
            }
            if ($actualHash -ne [string]$item.sha256) {
                throw "Member hash mismatch: $($item.path)"
            }
        }
        if (@($manifest.files).Count + 1 -ne $entries.Count) {
            throw "ZIP contains members not declared by manifest"
        }
        return @{
            FileCount = $entries.Count
            AcceptedChapters = [int]$manifest.counts.accepted_manuscript_chapters
            ManifestSha256 = $manifestHash
        }
    }
    finally {
        $archive.Dispose()
    }
}

try {
    Set-Location $repoRoot
    Write-Output "[1/5] Restart Backend with export route"
    docker-compose restart backend
    if ($LASTEXITCODE -ne 0) { throw "Backend restart failed" }

    Write-Output "[2/5] Wait for Backend"
    $healthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:18080/api/v1/health
            if ($health.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthy) { throw "Backend health check failed" }

    if (-not $NovelId) {
        $NovelId = docker-compose exec -T backend python -c "import sqlite3; c=sqlite3.connect('/app/data/novels.db'); r=c.execute('SELECT novel_id FROM manuscript_chapters WHERE accepted_revision IS NOT NULL GROUP BY novel_id ORDER BY COUNT(*) DESC, novel_id LIMIT 1').fetchone(); print(r[0] if r else '')"
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect accepted Manuscript scope" }
        $NovelId = $NovelId.Trim()
    }
    if (-not $NovelId) { throw "No novel with accepted Manuscript was found" }

    $encodedNovelId = [System.Uri]::EscapeDataString($NovelId)
    $uri = "http://127.0.0.1:18080/api/v1/novels/$encodedNovelId/export"
    Write-Output "[3/5] Download export twice"
    $first = Download-Archive $uri $archiveOne
    $second = Download-Archive $uri $archiveTwo

    Write-Output "[4/5] Verify manifest and every member"
    $verified = Verify-Archive $archiveOne $NovelId $first.ManifestSha256
    $secondVerified = Verify-Archive $archiveTwo $NovelId $second.ManifestSha256
    if ($verified.ManifestSha256 -ne $secondVerified.ManifestSha256) {
        throw "Repeat export manifest is not deterministic"
    }
    $archiveHashOne = (Get-FileHash -Algorithm SHA256 -LiteralPath $archiveOne).Hash
    $archiveHashTwo = (Get-FileHash -Algorithm SHA256 -LiteralPath $archiveTwo).Hash
    if ($archiveHashOne -ne $archiveHashTwo) {
        throw "Repeat export archive bytes are not deterministic"
    }
    if ($first.AcceptedChapters -ne $verified.AcceptedChapters) {
        throw "Accepted chapter response header mismatch"
    }

    Write-Output "[5/5] Report"
    Write-Output "EXPORT_DRILL=OK"
    Write-Output "NOVEL_ID=$NovelId"
    Write-Output "BACKEND_STATUS=$($first.StatusCode)"
    Write-Output "FILES=$($verified.FileCount)"
    Write-Output "ACCEPTED_CHAPTERS=$($verified.AcceptedChapters)"
    Write-Output "MANIFEST_SHA256=$($verified.ManifestSha256)"
    Write-Output "DETERMINISTIC=true"
}
finally {
    foreach ($path in @($archiveOne, $archiveTwo)) {
        $resolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $path))
        if ($resolvedParent -eq $tempRoot -and [System.IO.File]::Exists($path)) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}
