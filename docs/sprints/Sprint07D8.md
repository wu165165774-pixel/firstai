# Sprint 07D.8 — Backpressure, Timeout and Worker Control

## Release
- Version: `v0.15.0-alpha.9`
- Baseline: `v0.15.0-alpha.8`

## Features
- Global queued/retry-wait limit via `NOVELFORGE_WORKFLOW_MAX_QUEUED_JOBS`
- Per-user active-run quota via `NOVELFORGE_WORKFLOW_MAX_ACTIVE_PER_USER`
- HTTP 429 `queue_full` and `user_quota_exceeded`
- Idempotency checked before backpressure
- Per-attempt timeout via `X-Workflow-Timeout-Seconds`
- Default timeout via `NOVELFORGE_WORKFLOW_TIMEOUT_SECONDS`
- Timeout event `run_attempt_timed_out`
- Timeout retry and DLQ integration
- Worker `pause`, `resume`, and `drain`
- Persistent backpressure/timeout counters
- SQLite in-place migration

## Worker control APIs
```text
POST /api/v1/workflows/workers/{worker_id}/pause
POST /api/v1/workflows/workers/{worker_id}/resume
POST /api/v1/workflows/workers/{worker_id}/drain
```

## Production defaults
```text
NOVELFORGE_WORKFLOW_MAX_QUEUED_JOBS=1000
NOVELFORGE_WORKFLOW_MAX_ACTIVE_PER_USER=8
NOVELFORGE_WORKFLOW_TIMEOUT_SECONDS=900
```

## SQLite changes
`workflow_run_jobs`:
```text
timeout_seconds
timed_out_count
```

`workflow_workers`:
```text
control_mode
control_updated_at
```

New persistent structures:
```text
workflow_queue_counters
idx_workflow_workers_control
```

## Automated tests
```text
Ran 113 tests
OK
```

## Real acceptance
Temporary acceptance policy:
```text
max_queued_jobs = 2
max_active_per_user = 1
default_timeout_seconds = 0.1
```

Verified:
```text
WORKER PAUSE: PASS
IDEMPOTENCY UNDER BACKPRESSURE: PASS
GLOBAL QUEUE BACKPRESSURE: PASS
PER-USER QUOTA: PASS
WORKER DRAIN: PASS
WORKER RESUME: PASS
REAL EXECUTION TIMEOUT: PASS
BACKPRESSURE METRICS: PASS
PRODUCTION POLICY RESTORE: PASS
WORKER RESTORE: PASS
```

Global backpressure:
```text
HTTP 429
code = queue_full
retry-after = 1
```

Per-user quota:
```text
HTTP 429
code = user_quota_exceeded
```

Real timeout Run:
```text
b484f825-be33-45a1-9e15-6e5f77114410
```

Timeout result:
```text
attempt_count = 2
timed_out_count = 2
run_attempt_timed_out = 2
retry_scheduled = 1
run_dead_lettered = 1
```

Metrics delta:
```text
queue_full_rejections_delta = 1
user_quota_rejections_delta = 1
timeout_failures_delta = 2
```

Production restore:
```text
max_queued_jobs = 1000
max_active_per_user = 8
default_timeout_seconds = 900.0
running standalone worker = 1
```
