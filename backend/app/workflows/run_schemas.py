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
    "running",
    "succeeded",
    "resumable",
    "failed",
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
