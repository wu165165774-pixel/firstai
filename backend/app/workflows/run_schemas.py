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
