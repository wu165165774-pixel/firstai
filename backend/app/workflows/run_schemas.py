from __future__ import annotations

from typing import (
    Any,
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResult,
)


WorkflowExecutionStatus = Literal[
    "queued",
    "running",
    "retrying",
    "cancelling",
    "cancelled",
    "succeeded",
    "resumable",
    "failed",
    "dead_letter",
]


class WorkflowRunSummary(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    run_id: str

    root_run_id: str

    parent_run_id: str | None = None

    user_id: str

    novel_id: str

    workflow_type: str = (
        "chapter_production"
    )

    execution_status: (
        WorkflowExecutionStatus
    )

    workflow_status: str | None = None

    quality_gate_passed: bool = False

    resumable: bool = False

    revision_rounds: int = 0

    latest_content_length: int = 0

    error: str | None = None

    created_at: str

    updated_at: str

    completed_at: str | None = None


class WorkflowRunEvent(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    event_id: str

    run_id: str

    sequence_no: int = Field(
        ge=0
    )

    event_type: str

    stage: str | None = None

    round_index: int | None = None

    attempt_index: int | None = None

    payload: dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: str


class WorkflowChapterVersion(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    version_id: str

    run_id: str

    version_index: int = Field(
        ge=0
    )

    source_stage: str

    round_index: int = Field(
        ge=0
    )

    content: str

    content_hash: str

    created_at: str


class WorkflowRunDetail(
    WorkflowRunSummary
):

    request: ChapterWorkflowRequest

    result: (
        ChapterWorkflowResult
        | None
    ) = None

    latest_content: str = ""

    events: list[
        WorkflowRunEvent
    ] = Field(
        default_factory=list
    )

    versions: list[
        WorkflowChapterVersion
    ] = Field(
        default_factory=list
    )


class WorkflowRunResponse(BaseModel):

    code: int = 0

    message: str = "success"

    data: WorkflowRunDetail


class WorkflowRunListResponse(BaseModel):

    code: int = 0

    message: str = "success"

    data: list[
        WorkflowRunSummary
    ] = Field(
        default_factory=list
    )


class WorkflowResumeRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    request_overrides: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

WorkflowJobQueueStatus = Literal[
    "queued",
    "retry_wait",
    "running",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
    "dead_letter",
]


class WorkflowJobControl(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    run_id: str

    queue_status: (
        WorkflowJobQueueStatus
    )

    idempotency_key: str | None = None

    priority: int = Field(
        default=0,
        ge=-100,
        le=100,
    )

    attempt_count: int = Field(
        default=0,
        ge=0,
    )

    max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
    )

    retry_base_seconds: float = Field(
        default=2.0,
        ge=0.01,
        le=3600.0,
    )

    timeout_seconds: float = Field(
        default=900.0,
        ge=0.1,
        le=86400.0,
    )

    timed_out_count: int = Field(
        default=0,
        ge=0,
    )

    available_at: str

    last_error: str | None = None

    dead_lettered_at: str | None = None

    cancel_requested: bool = False

    lease_owner: str | None = None

    lease_expires_at: str | None = None

    heartbeat_at: str | None = None

    queued_at: str

    claimed_at: str | None = None

    updated_at: str


class WorkflowAsyncSubmission(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    run: WorkflowRunDetail

    job: WorkflowJobControl

    deduplicated: bool = False


class WorkflowAsyncSubmissionResponse(
    BaseModel
):

    code: int = 0

    message: str = "success"

    data: WorkflowAsyncSubmission

WorkflowWorkerStatus = Literal[
    "running",
    "stopping",
    "stopped",
    "stale",
]


class WorkflowWorkerInfo(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    worker_id: str

    worker_status: WorkflowWorkerStatus

    capacity: int = Field(
        ge=1
    )

    active_count: int = Field(
        ge=0
    )

    started_at: str

    heartbeat_at: str

    stopped_at: str | None = None

    control_mode: Literal[
        "running",
        "paused",
        "draining",
    ] = "running"

    accepting_work: bool = True

    control_updated_at: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class WorkflowWorkerListResponse(
    BaseModel
):

    code: int = 0

    message: str = "success"

    data: list[
        WorkflowWorkerInfo
    ] = Field(
        default_factory=list
    )

class WorkflowQueueRetryRequest(
    BaseModel
):

    model_config = ConfigDict(
        extra="forbid"
    )

    reset_attempts: bool = True

    priority: int | None = Field(
        default=None,
        ge=-100,
        le=100,
    )

    max_attempts: int | None = Field(
        default=None,
        ge=1,
        le=10,
    )

    retry_base_seconds: float | None = Field(
        default=None,
        ge=0.01,
        le=3600.0,
    )

    timeout_seconds: float | None = Field(
        default=None,
        ge=0.1,
        le=86400.0,
    )


class WorkflowQueueMetrics(
    BaseModel
):

    model_config = ConfigDict(
        extra="forbid"
    )

    total_jobs: int = Field(
        ge=0
    )

    status_counts: dict[
        str,
        int,
    ] = Field(
        default_factory=dict
    )

    ready_count: int = Field(
        ge=0
    )

    delayed_retry_count: int = Field(
        ge=0
    )

    dead_letter_count: int = Field(
        ge=0
    )

    priority_min: int | None = None

    priority_max: int | None = None

    priority_average: float | None = None

    max_queued_jobs: int = Field(
        default=1000,
        ge=0,
    )

    max_active_per_user: int = Field(
        default=8,
        ge=0,
    )

    default_timeout_seconds: float = Field(
        default=900.0,
        ge=0.1,
        le=86400.0,
    )

    backpressure_active: bool = False

    queue_full_rejections: int = Field(
        default=0,
        ge=0,
    )

    user_quota_rejections: int = Field(
        default=0,
        ge=0,
    )

    timeout_failures: int = Field(
        default=0,
        ge=0,
    )

    observation_window_seconds: float = Field(
        default=300.0,
        ge=1.0,
        le=86400.0,
    )

    terminal_in_window: int = Field(default=0, ge=0)
    completed_in_window: int = Field(default=0, ge=0)
    failed_in_window: int = Field(default=0, ge=0)
    dead_lettered_in_window: int = Field(default=0, ge=0)
    cancelled_in_window: int = Field(default=0, ge=0)
    throughput_per_minute: float = Field(default=0.0, ge=0.0)
    success_throughput_per_minute: float = Field(default=0.0, ge=0.0)
    queue_latency_samples: int = Field(default=0, ge=0)
    queue_latency_seconds_average: float | None = Field(default=None, ge=0.0)
    queue_latency_seconds_max: float | None = Field(default=None, ge=0.0)
    execution_duration_samples: int = Field(default=0, ge=0)
    execution_duration_seconds_average: float | None = Field(default=None, ge=0.0)
    execution_duration_seconds_max: float | None = Field(default=None, ge=0.0)
    oldest_ready_age_seconds: float | None = Field(default=None, ge=0.0)
    archived_job_count: int = Field(default=0, ge=0)
    dlq_replayed_total: int = Field(default=0, ge=0)
    archived_jobs_total: int = Field(default=0, ge=0)

    worker_status_counts: dict[
        str,
        int,
    ] = Field(
        default_factory=dict
    )


class WorkflowQueueMetricsResponse(
    BaseModel
):

    code: int = 0

    message: str = "success"

    data: WorkflowQueueMetrics


class WorkflowDeadLetterEntry(
    BaseModel
):

    model_config = ConfigDict(
        extra="forbid"
    )

    run_id: str

    user_id: str

    novel_id: str

    priority: int

    attempt_count: int = Field(
        ge=0
    )

    max_attempts: int = Field(
        ge=1
    )

    retry_base_seconds: float = Field(
        ge=0.01
    )

    last_error: str | None = None

    dead_lettered_at: str | None = None

    updated_at: str


class WorkflowDeadLetterListResponse(
    BaseModel
):

    code: int = 0

    message: str = "success"

    data: list[
        WorkflowDeadLetterEntry
    ] = Field(
        default_factory=list
    )

class WorkflowWorkerControlResponse(
    BaseModel
):

    code: int = 0

    message: str = "success"

    data: WorkflowWorkerInfo

class WorkflowDeadLetterReplayRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    run_ids: list[str] = Field(
        min_length=1,
        max_length=100,
    )
    reset_attempts: bool = True
    priority: int | None = Field(default=None, ge=-100, le=100)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    retry_base_seconds: float | None = Field(default=None, ge=0.01, le=3600.0)
    timeout_seconds: float | None = Field(default=None, ge=0.1, le=86400.0)


class WorkflowDeadLetterReplaySkipped(BaseModel):

    run_id: str
    reason: str


class WorkflowDeadLetterReplayResult(BaseModel):

    requested_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    replayed_run_ids: list[str] = Field(default_factory=list)
    skipped: list[WorkflowDeadLetterReplaySkipped] = Field(default_factory=list)


class WorkflowDeadLetterReplayResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: WorkflowDeadLetterReplayResult


class WorkflowQueueArchiveRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    older_than_seconds: float = Field(default=604800.0, ge=0.0, le=315360000.0)
    limit: int = Field(default=500, ge=1, le=5000)
    include_dead_letter: bool = False
    dry_run: bool = True


class WorkflowQueueArchiveResult(BaseModel):

    dry_run: bool
    candidate_count: int = Field(ge=0)
    archived_count: int = Field(ge=0)
    run_ids: list[str] = Field(default_factory=list)


class WorkflowQueueArchiveResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: WorkflowQueueArchiveResult


class WorkflowArchivedJobEntry(BaseModel):

    run_id: str
    user_id: str
    novel_id: str
    queue_status: str
    terminal_at: str
    archived_at: str


class WorkflowArchivedJobListResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: list[WorkflowArchivedJobEntry] = Field(default_factory=list)


class WorkflowWorkerClusterHealth(BaseModel):

    health_status: Literal["healthy", "degraded", "unavailable"]
    total_workers: int = Field(ge=0)
    running_workers: int = Field(ge=0)
    stale_workers: int = Field(ge=0)
    paused_workers: int = Field(ge=0)
    draining_workers: int = Field(ge=0)
    accepting_workers: int = Field(ge=0)
    total_capacity: int = Field(ge=0)
    active_count: int = Field(ge=0)
    available_slots: int = Field(ge=0)
    utilization: float = Field(ge=0.0)
    ready_count: int = Field(ge=0)


class WorkflowWorkerClusterHealthResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: WorkflowWorkerClusterHealth

class WorkflowWorkerBatchControlRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    worker_ids: list[str] = Field(
        min_length=1,
        max_length=100,
    )
    action: Literal[
        "pause",
        "resume",
        "drain",
    ]


class WorkflowWorkerBatchControlSkipped(BaseModel):

    worker_id: str
    reason: str


class WorkflowWorkerBatchControlResult(BaseModel):

    requested_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    workers: list[WorkflowWorkerInfo] = Field(
        default_factory=list
    )
    skipped: list[
        WorkflowWorkerBatchControlSkipped
    ] = Field(default_factory=list)


class WorkflowWorkerBatchControlResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: WorkflowWorkerBatchControlResult


class WorkflowWorkerHistoryCleanupRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    older_than_seconds: float = Field(
        default=604800.0,
        ge=0.0,
        le=315360000.0,
    )
    stale_after_seconds: float = Field(
        default=90.0,
        ge=1.0,
        le=86400.0,
    )
    include_stale_running: bool = True
    limit: int = Field(
        default=500,
        ge=1,
        le=5000,
    )
    dry_run: bool = True


class WorkflowWorkerHistoryCleanupResult(BaseModel):

    dry_run: bool
    candidate_count: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    worker_ids: list[str] = Field(
        default_factory=list
    )


class WorkflowWorkerHistoryCleanupResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: WorkflowWorkerHistoryCleanupResult


class WorkflowOperationAuditEntry(BaseModel):

    audit_id: str
    operation_type: str
    target_type: str
    target_id: str | None = None
    action: str
    status: str
    created_at: str
    details: dict[str, Any] = Field(
        default_factory=dict
    )


class WorkflowOperationAuditListResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: list[
        WorkflowOperationAuditEntry
    ] = Field(default_factory=list)


class WorkflowOperationalAlert(BaseModel):

    code: str
    severity: Literal[
        "warning",
        "critical",
    ]
    message: str
    value: Any = None
    threshold: Any = None


class WorkflowOperationsDashboard(BaseModel):

    generated_at: str
    alert_status: Literal[
        "ok",
        "warning",
        "critical",
    ]
    alerts: list[
        WorkflowOperationalAlert
    ] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(
        default_factory=dict
    )
    queue: WorkflowQueueMetrics
    workers: WorkflowWorkerClusterHealth
    recent_audit: list[
        WorkflowOperationAuditEntry
    ] = Field(default_factory=list)


class WorkflowOperationsDashboardResponse(BaseModel):

    code: int = 0
    message: str = "success"
    data: WorkflowOperationsDashboard
