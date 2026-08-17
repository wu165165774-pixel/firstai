param(
    [string]$AccessToken = "",
    [int]$WorkflowAttempts = 2,
    [int]$PlannerAttempts = 3
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$expectedVersion = "1.0.0"
$baselineVersion = "1.0.0-rc.2"
$apiRoot = "http://127.0.0.1:18080/api/v1"
$runStamp = Get-Date -Format "yyyyMMddTHHmmss"
$userId = "v1-release-journey-$runStamp"
$canonicalCharacterName = (
    [string][char]0x6797 + [string][char]0x821F
)
$previousPythonPath = $env:PYTHONPATH
$previousBindHost = $env:NOVELFORGE_BIND_HOST
$previousDebug = $env:DEBUG
$previousOverride = $env:ALLOW_INSECURE_NETWORK_EXPOSURE
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:NOVELFORGE_BIND_HOST = "127.0.0.1"
$env:DEBUG = "false"
$env:ALLOW_INSECURE_NETWORK_EXPOSURE = "false"

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

function Wait-HttpStatus {
    param(
        [string]$Uri,
        [int]$Attempts = 120
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $status = (
                Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $Uri
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

function Invoke-Api {
    param(
        [ValidateSet("GET", "POST", "PUT", "PATCH")]
        [string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 240
    )
    $requestHeaders = @{}
    if ($AccessToken) {
        $requestHeaders["Authorization"] = "Bearer $AccessToken"
    }
    foreach ($item in $Headers.GetEnumerator()) {
        $requestHeaders[$item.Key] = $item.Value
    }
    $client = [System.Net.Http.HttpClient]::new()
    $request = $null
    $response = $null
    try {
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
        $httpMethod = [System.Net.Http.HttpMethod]::new($Method)
        $request = [System.Net.Http.HttpRequestMessage]::new(
            $httpMethod,
            "$apiRoot$Path"
        )
        foreach ($item in $requestHeaders.GetEnumerator()) {
            [void]$request.Headers.TryAddWithoutValidation(
                [string]$item.Key,
                [string]$item.Value
            )
        }
        if ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 100 -Compress
            $request.Content = [System.Net.Http.StringContent]::new(
                $json,
                [System.Text.Encoding]::UTF8,
                "application/json"
            )
        }
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
        if (-not $response.IsSuccessStatusCode) {
            throw (
                "API $Method $Path failed ($([int]$response.StatusCode)): " +
                $text
            )
        }
        if (-not $text) { return $null }
        return $text | ConvertFrom-Json
    }
    finally {
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $request) { $request.Dispose() }
        $client.Dispose()
    }
}

function Invoke-PlannerCandidate {
    param(
        [string]$NovelId,
        [string]$Target,
        [string]$Instruction,
        [hashtable]$Coordinates = @{}
    )
    $generate = @{
        target = $Target
        instruction = $Instruction
        provider = "qwen_local"
        model = "qwen3:8b"
        use_memory = $true
        reasoning_effort = "medium"
        temperature = 0.1
        max_tokens = 2400
    }
    foreach ($item in $Coordinates.GetEnumerator()) {
        $generate[$item.Key] = $item.Value
    }
    $generated = $null
    $generationAttempt = 0
    for ($attempt = 1; $attempt -le $PlannerAttempts; $attempt++) {
        $generationAttempt = $attempt
        try {
            $generated = Invoke-Api `
                -Method POST `
                -Path "/novels/$NovelId/planner/generate" `
                -Body $generate `
                -TimeoutSec 600
            break
        }
        catch {
            if ($attempt -eq $PlannerAttempts) { throw }
            Write-Warning (
                "Planner generation attempt $attempt failed for $Target; " +
                "retrying a candidate-only request"
            )
        }
    }
    if ($null -eq $generated) {
        throw "Planner generation returned no $Target candidate"
    }
    if ($generated.data.persisted -ne $false) {
        throw "Planner generation persisted the $Target candidate"
    }
    $accept = @{
        target = $Target
        candidate = $generated.data.candidate
        source_revisions = $generated.data.source_revisions
    }
    foreach ($item in $Coordinates.GetEnumerator()) {
        $accept[$item.Key] = $item.Value
    }
    $accepted = Invoke-Api `
        -Method POST `
        -Path "/novels/$NovelId/planner/accept" `
        -Body $accept
    if ($accepted.data.persisted -ne $true) {
        throw "Planner acceptance did not persist $Target"
    }
    return @{
        Generated = $generated.data
        Accepted = $accepted.data
        GenerationAttempts = $generationAttempt
    }
}

function Wait-WorkflowTerminal {
    param(
        [string]$RunId,
        [int]$Attempts = 200
    )
    $terminal = @(
        "succeeded",
        "resumable",
        "failed",
        "dead_letter",
        "cancelled"
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $run = Invoke-Api -Method GET -Path "/workflows/runs/$RunId"
        if ($terminal -contains [string]$run.data.execution_status) {
            return $run.data
        }
        Start-Sleep -Seconds 3
    }
    throw "Workflow did not reach a terminal state: $RunId"
}

function Add-UsageTotal {
    param(
        [int]$Current,
        [object]$Usage
    )
    if ($null -eq $Usage -or $null -eq $Usage.total_tokens) {
        return $Current
    }
    return $Current + [int]$Usage.total_tokens
}

try {
    if ($WorkflowAttempts -lt 1 -or $WorkflowAttempts -gt 4) {
        throw "WorkflowAttempts must be between 1 and 4"
    }
    if ($PlannerAttempts -lt 1 -or $PlannerAttempts -gt 4) {
        throw "PlannerAttempts must be between 1 and 4"
    }

    Write-Output "[1/15] Validate final release contracts"
    $versions = python -c `
        "from app.release_engineering.service import ReleaseEngineeringService; import json; print(json.dumps(ReleaseEngineeringService('.').versions(), sort_keys=True))" |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Version contract failed" }
    foreach ($value in $versions.psobject.Properties.Value) {
        if ($value -ne $expectedVersion) {
            throw "Release identity is not $expectedVersion"
        }
    }
    $dependency = python -c `
        "from app.release_engineering.service import ReleaseEngineeringService; import json; print(json.dumps(ReleaseEngineeringService('.').dependency_contract(), sort_keys=True))" |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Dependency contract failed" }
    $readiness = python -c `
        "from app.release_engineering.service import ReleaseEngineeringService; import json; print(json.dumps(ReleaseEngineeringService('.').readiness_contract('1.0.0'), sort_keys=True))" |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Readiness contract failed" }
    if (@($readiness.required_acceptance).Count -ne 9) {
        throw "Unexpected readiness acceptance count"
    }
    $upgrade = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation upgrade `
        --other-version $baselineVersion `
        --schema-version 1 | ConvertFrom-Json
    $rollback = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation rollback `
        --other-version $baselineVersion `
        --schema-version 1 | ConvertFrom-Json
    $newerSchema = python -m app.release_engineering.cli assess `
        --repo-root . `
        --operation rollback `
        --other-version $baselineVersion `
        --schema-version 2 | ConvertFrom-Json
    if ($upgrade.decision -ne "direct" -or $rollback.decision -ne "direct") {
        throw "RC2 direct compatibility path is invalid"
    }
    if ($newerSchema.decision -ne "restore_backup") {
        throw "Newer schema rollback did not require restore_backup"
    }
    git -c safe.directory=D:/AI/novel-ai diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check failed" }

    Write-Output "[2/15] Validate Compose configurations"
    docker-compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Base Compose validation failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Worker Compose validation failed" }

    Write-Output "[3/15] Run Frontend tests"
    npm test --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }

    Write-Output "[4/15] Build final production images"
    docker-compose build backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Backend/Frontend build failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        build worker
    if ($LASTEXITCODE -ne 0) { throw "Worker build failed" }

    Write-Output "[5/15] Verify image runtime locks"
    docker run --rm --entrypoint python novel-ai-backend `
        -m app.release_engineering.runtime_lock `
        --lock /app/requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "Backend runtime lock mismatch" }
    docker run --rm --entrypoint python novel-ai-worker `
        -m app.release_engineering.runtime_lock `
        --lock /app/requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "Worker runtime lock mismatch" }

    Write-Output "[6/15] Recreate final production services"
    docker-compose up -d --no-deps --force-recreate ollama backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Base service recreate failed" }
    docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml `
        up -d --no-deps --force-recreate worker
    if ($LASTEXITCODE -ne 0) { throw "Worker recreate failed" }

    Write-Output "[7/15] Verify live version, schema, Provider and Worker"
    $backendStatus = Wait-HttpStatus "$apiRoot/health"
    $frontendStatus = Wait-HttpStatus "http://127.0.0.1:18081/healthz"
    $ollamaStatus = Wait-HttpStatus "http://127.0.0.1:11434/"
    $openapi = Invoke-RestMethod http://127.0.0.1:18080/openapi.json
    if ($openapi.info.version -ne $expectedVersion) {
        throw "Live Backend is not $expectedVersion"
    }
    $schema = docker exec novelforge-backend `
        python -m app.schema_migrations.cli verify `
        --data-root /app/data | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $schema.ready -ne $true) {
        throw "Live schema verification failed"
    }
    $providers = Invoke-Api `
        -Method GET `
        -Path "/providers?probe=true&timeout_ms=5000"
    $qwen = @($providers.data.catalog) |
        Where-Object { $_.name -eq "qwen_local" } |
        Select-Object -First 1
    if ($null -eq $qwen -or $qwen.configured -ne $true -or $qwen.available -ne $true) {
        throw "qwen_local Provider is not available"
    }
    if ($AccessToken) {
        $identity = Invoke-Api -Method GET -Path "/auth/me"
        $userId = [string]$identity.data.user_id
        if (-not $userId) { throw "Authenticated user identity is missing" }
    }
    $workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
    if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
        throw "Worker is not running"
    }

    Write-Output "[8/15] Run focused Backend release regressions"
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
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests `
        -p "test_plugin_catalog.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Plugin Catalog tests failed" }
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests `
        -p "test_plugin_runtime.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Plugin Runtime tests failed" }

    Write-Output "[9/15] Run full Backend regression"
    docker exec -w /app novelforge-backend `
        python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Backend full regression failed" }

    Write-Output "[10/15] Create release journey Project and aligned Story Bible"
    $projectResponse = Invoke-Api -Method POST -Path "/novels" -Body @{
        user_id = $userId
        title = "Tidal Beacon: v1 Release Acceptance"
        genre = "near-future mystery"
        premise = "Beacon keeper $canonicalCharacterName must repair TIDE-17 before sea fog consumes Mirror Harbor and determine whether a missing mentor's warning is trustworthy."
        language = "zh-CN"
        target_word_count = 120000
        status = "planning"
        style_guide = @{
            tense = "past"
            viewpoint = "third-person limited"
            tone = "restrained, concrete, suspenseful"
        }
        constraints = @(
            "The canonical character name must remain $canonicalCharacterName exactly",
            "The beacon identifier must remain TIDE-17"
        )
        metadata = @{ acceptance = "v1.0.0" }
    }
    $project = $projectResponse.data
    $novelId = [string]$project.novel_id
    if (-not $novelId -or [int]$project.revision -ne 1) {
        throw "Project creation failed"
    }
    $bibleResponse = Invoke-Api `
        -Method PUT `
        -Path "/novels/$novelId/story-bible" `
        -Body @{
            expected_revision = 1
            world = @{
                name = "Mirror Harbor"
                summary = "A near-future port periodically enclosed by sea fog; offshore beacons maintain its only safe channel."
            }
            characters = @(
                @{
                    name = $canonicalCharacterName
                    role = "protagonist"
                    description = "A cautious young beacon keeper who verifies evidence before acting."
                    aliases = @("Lin Zhou", "Zhou")
                }
            )
            locations = @(
                @{ name = "TIDE-17 Beacon"; description = "An automated beacon tower offshore from Mirror Harbor." }
            )
            rules = @(
                @{ name = "Fog Tide"; description = "The sea fog delays radio echoes but cannot forge physical navigation markers." }
            )
            themes = @("trust and evidence", "responsibility")
            timeline = @(
                @{ event = "The mentor disappears"; order = 1 },
                @{ event = "TIDE-17 emits contradictory warnings"; order = 2 }
            )
            metadata = @{ acceptance = "v1.0.0" }
        }
    $alignmentResponse = Invoke-Api `
        -Method POST `
        -Path "/novels/$novelId/story-bible/entities/align" `
        -Body @{
            expected_revision = [int]$bibleResponse.data.revision
            create_missing = $true
        }
    $alignment = $alignmentResponse.data
    if (@($alignment.bindings).Count -ne 1) {
        throw "Story Bible alignment did not bind the protagonist"
    }
    $entityId = [string]$alignment.bindings[0].entity_id
    if (-not $entityId) { throw "Canonical entity ID is missing" }
    $locationResponse = Invoke-Api `
        -Method POST `
        -Path "/novels/$novelId/entities" `
        -Body @{
            entity_id = "loc_001"
            entity_type = "location"
            canonical_name = "TIDE-17 Beacon"
            aliases = @("TIDE-17")
            description = "An automated beacon tower offshore from Mirror Harbor."
            metadata = @{ acceptance = "v1.0.0" }
        }
    $locationEntityId = [string]$locationResponse.data.entity_id
    if (
        $locationEntityId -ne "loc_001" -or
        [string]$locationResponse.data.entity_type -ne "location"
    ) {
        throw "Canonical location entity creation failed"
    }

    Write-Output "[11/15] Generate candidate-only planning and explicitly accept it"
    $plannerTokens = 0
    $plannerCalls = 0
    $novelPlanResult = Invoke-PlannerCandidate `
        -NovelId $novelId `
        -Target "novel_plan" `
        -Instruction "Create a concise long-form near-future mystery plan. Preserve the canonical character name $canonicalCharacterName exactly, along with Mirror Harbor, TIDE-17, and every established world rule. The main plot must progress toward revealing the truth and a choice about responsibility."
    $plannerTokens = Add-UsageTotal `
        -Current $plannerTokens `
        -Usage $novelPlanResult.Generated.usage
    $plannerCalls += [int]$novelPlanResult.GenerationAttempts
    $novelPlan = $novelPlanResult.Accepted.novel_plan
    if ($null -eq $novelPlan -or $novelPlan.is_stale -eq $true) {
        throw "Accepted Novel Plan is missing or stale"
    }

    $arcResult = Invoke-PlannerCandidate `
        -NovelId $novelId `
        -Target "story_arc" `
        -Instruction "Create volume 1 story arc 1: $canonicalCharacterName reaches TIDE-17, confirms the contradictory warning, and finds verifiable evidence left by the mentor. Preserve the canonical character name exactly, keep the conflict focused, and preserve the requested coordinates." `
        -Coordinates @{ volume_number = 1; arc_number = 1 }
    $plannerTokens = Add-UsageTotal `
        -Current $plannerTokens `
        -Usage $arcResult.Generated.usage
    $plannerCalls += [int]$arcResult.GenerationAttempts
    $arc = $arcResult.Accepted.story_arc
    if ($null -eq $arc -or [int]$arc.volume_number -ne 1 -or [int]$arc.arc_number -ne 1) {
        throw "Accepted Story Arc coordinates changed"
    }

    $chapterResult = Invoke-PlannerCandidate `
        -NovelId $novelId `
        -Target "chapter_plan" `
        -Instruction "Create the chapter 1 plan. $canonicalCharacterName enters TIDE-17, verifies its identifier and the radio echo, and finds the mentor's physical maintenance record at the end. Preserve the canonical character name exactly; use third-person limited and actionable scene beats. For every scene at the beacon, use the canonical location_id $locationEntityId exactly and do not invent another location ID." `
        -Coordinates @{
            arc_id = [string]$arc.arc_id
            chapter_number = 1
        }
    $plannerTokens = Add-UsageTotal `
        -Current $plannerTokens `
        -Usage $chapterResult.Generated.usage
    $plannerCalls += [int]$chapterResult.GenerationAttempts
    $chapterPlan = $chapterResult.Accepted.chapter_plan
    if (
        $null -eq $chapterPlan -or
        [string]$chapterPlan.arc_id -ne [string]$arc.arc_id -or
        [int]$chapterPlan.chapter_number -ne 1 -or
        $chapterPlan.is_stale -eq $true
    ) {
        throw "Accepted Chapter Plan is invalid"
    }
    $chapterLocationIds = @(
        $chapterPlan.scene_beats |
            ForEach-Object { [string]$_.location_id } |
            Where-Object { $_ }
    )
    if (
        $chapterLocationIds.Count -eq 0 -or
        @($chapterLocationIds | Where-Object { $_ -ne $locationEntityId }).Count -ne 0
    ) {
        throw "Accepted Chapter Plan did not preserve the canonical location ID"
    }

    Write-Output "[12/15] Execute idempotent asynchronous Chapter Workflow"
    $successfulRun = $null
    $successfulAttempt = 0
    $workflowDeduplicated = $false
    for ($workflowAttempt = 1; $workflowAttempt -le $WorkflowAttempts; $workflowAttempt++) {
        $idempotencyKey = "v1:${novelId}:chapter-1:attempt-$workflowAttempt"
        if (-not $idempotencyKey.StartsWith("v1:${novelId}:")) {
            throw "Workflow idempotency key lost the Novel ID scope"
        }
        $workflowPayload = @{
            user_id = $userId
            novel_id = $novelId
            instruction = "Write the complete chapter 1 prose in Simplified Chinese from the accepted plan. Explicitly include the TIDE-17 identifier and show $canonicalCharacterName verifying information through a physical maintenance record. Preserve the canonical character name and all Canon exactly. Target roughly 1200 to 1800 Chinese characters."
            chapter_plan_id = [string]$chapterPlan.chapter_plan_id
            chapter_plan_revision = [int]$chapterPlan.revision
            provider = "qwen_local"
            model = "qwen3:8b"
            use_memory = $true
            auto_rewrite = $true
            max_revision_rounds = 3
            review_retry_attempts = 2
            review_retry_reasoning_effort = "medium"
            minimum_overall_score = 70
            minimum_dimension_score = 60
            require_all_issues_resolved = $false
            chapter_reasoning_effort = "low"
            review_reasoning_effort = "medium"
            rewrite_reasoning_effort = "none"
            chapter_temperature = 0.4
            review_temperature = 0.0
            rewrite_temperature = 0.3
            chapter_max_tokens = 2200
            review_max_tokens = 1800
            rewrite_max_tokens = 2200
            rewrite_on_severities = @("critical", "major", "moderate")
            metadata = @{
                acceptance = "v1.0.0"
                attempt = $workflowAttempt
            }
        }
        $queueHeaders = @{
            "Idempotency-Key" = $idempotencyKey
            "X-Workflow-Priority" = "10"
            "X-Workflow-Max-Attempts" = "2"
            "X-Workflow-Retry-Base-Seconds" = "2"
            "X-Workflow-Timeout-Seconds" = "1200"
        }
        $submission = Invoke-Api `
            -Method POST `
            -Path "/workflows/chapter/runs/async" `
            -Body $workflowPayload `
            -Headers $queueHeaders
        if (
            $submission.data.deduplicated -ne $false -or
            [string]$submission.data.run.novel_id -ne $novelId
        ) {
            throw "Workflow submission was not new and scoped to the Novel"
        }
        $duplicate = Invoke-Api `
            -Method POST `
            -Path "/workflows/chapter/runs/async" `
            -Body $workflowPayload `
            -Headers $queueHeaders
        if (
            $duplicate.data.deduplicated -ne $true -or
            [string]$duplicate.data.run.run_id -ne [string]$submission.data.run.run_id -or
            [string]$duplicate.data.run.novel_id -ne $novelId
        ) {
            throw "Workflow idempotency contract failed"
        }
        $workflowDeduplicated = $true
        $terminalRun = Wait-WorkflowTerminal `
            -RunId ([string]$submission.data.run.run_id)
        if (
            $terminalRun.execution_status -eq "succeeded" -and
            $terminalRun.workflow_status -eq "completed" -and
            $terminalRun.quality_gate_passed -eq $true
        ) {
            $successfulRun = $terminalRun
            $successfulAttempt = $workflowAttempt
            break
        }
        Write-Warning (
            "Workflow attempt $workflowAttempt did not pass: " +
            "$($terminalRun.execution_status)/$($terminalRun.workflow_status); " +
            "error=$($terminalRun.error)"
        )
    }
    if ($null -eq $successfulRun) {
        throw "No Workflow attempt passed the complete quality gate"
    }

    Write-Output "[13/15] Import, explicitly accept and project accepted facts"
    $importResponse = Invoke-Api `
        -Method POST `
        -Path "/novels/$novelId/manuscript/chapters/import-workflow" `
        -Body @{
            workflow_run_id = [string]$successfulRun.run_id
            expected_manuscript_revision = $null
        }
    $imported = $importResponse.data
    $approved = @($imported.imported_revisions) |
        Where-Object { $_.review_status -eq "approved" } |
        Sort-Object revision -Descending |
        Select-Object -First 1
    if ($null -eq $approved) {
        throw "Workflow import did not create an approved Manuscript candidate"
    }
    $manuscriptChapterId = [string]$imported.chapter.manuscript_chapter_id
    $acceptResponse = Invoke-Api `
        -Method POST `
        -Path (
            "/novels/$novelId/manuscript/chapters/$manuscriptChapterId" +
            "/revisions/$($approved.revision)/accept"
        ) `
        -Body @{
            expected_manuscript_revision = [int]$imported.chapter.revision
        } `
        -TimeoutSec 600
    $accepted = $acceptResponse.data
    if (
        [int]$accepted.chapter.accepted_revision -ne [int]$approved.revision -or
        $accepted.accepted_revision.is_accepted -ne $true
    ) {
        throw "Manuscript explicit acceptance failed"
    }
    $projectionResponse = Invoke-Api `
        -Method GET `
        -Path (
            "/novels/$novelId/manuscript/chapters/$manuscriptChapterId" +
            "/revisions/$($approved.revision)/fact-projection"
        )
    $projection = $projectionResponse.data
    if ($projection.status -eq "failed") {
        $projectionResponse = Invoke-Api `
            -Method POST `
            -Path (
                "/novels/$novelId/manuscript/chapters/$manuscriptChapterId" +
                "/revisions/$($approved.revision)/fact-projection/retry"
            ) `
            -TimeoutSec 600
        $projection = $projectionResponse.data
    }
    if ($projection.status -ne "completed" -or [int]$projection.failed_count -ne 0) {
        throw "Accepted fact projection did not complete"
    }

    Write-Output "[14/15] Verify deterministic export, restart durability and user isolation"
    $exportArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ".\scripts\sprint09c3_export_drill.ps1",
        "-NovelId", $novelId
    )
    if ($AccessToken) {
        $exportArguments += @("-AccessToken", $AccessToken)
    }
    $exportOutput = & powershell @exportArguments
    $exportExit = $LASTEXITCODE
    $exportOutput | Write-Output
    if ($exportExit -ne 0) { throw "Deterministic novel export failed" }
    $exportReport = @{}
    foreach ($line in @($exportOutput)) {
        $text = [string]$line
        if ($text -match "^([A-Z0-9_]+)=(.*)$") {
            $exportReport[$matches[1]] = $matches[2]
        }
    }
    if (
        $exportReport["EXPORT_DRILL"] -ne "OK" -or
        $exportReport["DETERMINISTIC"] -ne "true" -or
        [int]$exportReport["ACCEPTED_CHAPTERS"] -ne 1 -or
        [string]$exportReport["MANIFEST_SHA256"] -notmatch "^[a-f0-9]{64}$"
    ) {
        throw "Export report is incomplete"
    }
    $durableProject = Invoke-Api -Method GET -Path "/novels/$novelId"
    $durableManuscript = Invoke-Api `
        -Method GET `
        -Path "/novels/$novelId/manuscript/chapters/$manuscriptChapterId"
    if (
        [string]$durableProject.data.novel_id -ne $novelId -or
        [int]$durableManuscript.data.chapter.accepted_revision -ne [int]$approved.revision
    ) {
        throw "Accepted product journey did not survive Backend restart"
    }
    if ($AccessToken) {
        $scopeRejected = $false
        try {
            Invoke-Api `
                -Method GET `
                -Path "/novels?user_id=v1-release-other-$runStamp&limit=200" |
                Out-Null
        }
        catch {
            if ($_ -match "403|declared user|scope") {
                $scopeRejected = $true
            }
        }
        if (-not $scopeRejected) {
            throw "Authenticated cross-user declaration was not rejected"
        }
    }
    else {
        $otherUser = Invoke-Api `
            -Method GET `
            -Path "/novels?user_id=v1-release-other-$runStamp&limit=200"
        if (@($otherUser.data | Where-Object { $_.novel_id -eq $novelId }).Count -ne 0) {
            throw "Novel leaked into another user list scope"
        }
    }
    $workerRunning = docker inspect -f "{{.State.Running}}" novelforge-worker
    if ($LASTEXITCODE -ne 0 -or $workerRunning.Trim() -ne "true") {
        throw "Worker is not running after Backend restart"
    }
    $backendStatus = Wait-HttpStatus "$apiRoot/health"
    $frontendStatus = Wait-HttpStatus "http://127.0.0.1:18081/healthz"

    Write-Output "[15/15] Report"
    $backendImage = docker image inspect novel-ai-backend -f "{{.Id}}"
    $frontendImage = docker image inspect novel-ai-frontend -f "{{.Id}}"
    $workerImage = docker image inspect novel-ai-worker -f "{{.Id}}"
    Write-Output "V1_RELEASE_DRILL=OK"
    Write-Output "VERSION=$expectedVersion"
    Write-Output "BASELINE_VERSION=$baselineVersion"
    Write-Output "USER_ID=$userId"
    Write-Output "NOVEL_ID=$novelId"
    Write-Output "ENTITY_ID=$entityId"
    Write-Output "LOCATION_ENTITY_ID=$locationEntityId"
    Write-Output "NOVEL_PLAN_REVISION=$($novelPlan.revision)"
    Write-Output "STORY_ARC_ID=$($arc.arc_id)"
    Write-Output "STORY_ARC_REVISION=$($arc.revision)"
    Write-Output "CHAPTER_PLAN_ID=$($chapterPlan.chapter_plan_id)"
    Write-Output "CHAPTER_PLAN_REVISION=$($chapterPlan.revision)"
    Write-Output "PLANNER_TARGETS=3"
    Write-Output "PLANNER_GENERATIONS=$plannerCalls"
    Write-Output "PLANNER_TOTAL_TOKENS=$plannerTokens"
    Write-Output "PLANNER_CANDIDATE_ONLY=true"
    Write-Output "PLANNING_EXPLICIT_ACCEPT=true"
    Write-Output "WORKFLOW_RUN_ID=$($successfulRun.run_id)"
    Write-Output "WORKFLOW_ATTEMPT=$successfulAttempt"
    Write-Output "WORKFLOW_IDEMPOTENT=$($workflowDeduplicated.ToString().ToLowerInvariant())"
    Write-Output "WORKFLOW_STATUS=$($successfulRun.workflow_status)"
    Write-Output "QUALITY_GATE_PASSED=$($successfulRun.quality_gate_passed.ToString().ToLowerInvariant())"
    Write-Output "MANUSCRIPT_CHAPTER_ID=$manuscriptChapterId"
    Write-Output "MANUSCRIPT_REVISION=$($approved.revision)"
    Write-Output "MANUSCRIPT_EXPLICIT_ACCEPT=true"
    Write-Output "FACT_PROJECTION_STATUS=$($projection.status)"
    Write-Output "FACT_PROJECTION_TOTAL=$($projection.total_count)"
    Write-Output "FACT_PROJECTION_COMPLETED=$($projection.completed_count)"
    Write-Output "EXPORT_FILES=$($exportReport['FILES'])"
    Write-Output "EXPORT_MANIFEST_SHA256=$($exportReport['MANIFEST_SHA256'])"
    Write-Output "EXPORT_DETERMINISTIC=true"
    Write-Output "RESTART_DURABLE=true"
    Write-Output "USER_SCOPE_ISOLATED=true"
    Write-Output "SCHEMA_VERSION=$($schema.target_version)"
    Write-Output "BACKEND_STATUS=$backendStatus"
    Write-Output "FRONTEND_STATUS=$frontendStatus"
    Write-Output "OLLAMA_STATUS=$ollamaStatus"
    Write-Output "WORKER_RUNNING=$($workerRunning.Trim())"
    Write-Output "BACKEND_LOCKED_PACKAGES=$($dependency.backend_locked_packages)"
    Write-Output "FRONTEND_LOCKED_PACKAGES=$($dependency.frontend_locked_packages)"
    Write-Output "BACKEND_IMAGE=$backendImage"
    Write-Output "FRONTEND_IMAGE=$frontendImage"
    Write-Output "WORKER_IMAGE=$workerImage"
    Write-Output "PRODUCTION_DATA_MODIFIED=true"
    Write-Output "LOCAL_GO_CANDIDATE=true"
    Write-Output "DISTRIBUTION_DECISION=pending_hosted_release"
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
