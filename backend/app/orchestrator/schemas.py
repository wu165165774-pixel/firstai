from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.llm.schemas import ReasoningEffort
from app.workflows.schemas import ReviewSeverity


NovelOrchestrationStatus = Literal[
    "ready",
    "waiting_for_workflow",
    "waiting_for_acceptance",
    "paused",
    "failed",
    "completed",
]

NovelOrchestrationStepStatus = Literal[
    "pending",
    "workflow_queued",
    "candidate_ready",
    "accepted",
    "failed",
]


class OrchestrationWorkflowPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction_template: str = Field(
        default=(
            "按已接受的章节规划写出第 {chapter_number} 章《{chapter_title}》"
            "完整正文，并承接此前已接受正文。"
        ),
        min_length=1,
        max_length=8000,
    )
    provider: str = Field(default="qwen_local", min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    use_memory: bool = True
    auto_rewrite: bool = True
    max_revision_rounds: int = Field(default=2, ge=0, le=5)
    review_retry_attempts: int = Field(default=1, ge=0, le=2)
    review_retry_reasoning_effort: ReasoningEffort = "none"
    minimum_overall_score: float = Field(default=80.0, ge=0.0, le=100.0)
    minimum_dimension_score: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
    )
    require_all_issues_resolved: bool = True
    chapter_reasoning_effort: ReasoningEffort = "low"
    review_reasoning_effort: ReasoningEffort = "medium"
    rewrite_reasoning_effort: ReasoningEffort = "none"
    chapter_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    review_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    rewrite_temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    chapter_max_tokens: int = Field(default=1600, gt=0)
    review_max_tokens: int = Field(default=1200, gt=0)
    rewrite_max_tokens: int = Field(default=1600, gt=0)
    rewrite_on_severities: list[ReviewSeverity] = Field(
        default_factory=lambda: ["critical", "major"]
    )
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationQueuePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: int = Field(default=0, ge=-100, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: float = Field(default=2.0, ge=0.01, le=3600.0)
    timeout_seconds: float = Field(default=900.0, ge=0.1, le=86400.0)


class NovelOrchestrationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=128)
    arc_ids: list[str] = Field(default_factory=list, max_length=1000)
    start_chapter_number: int | None = Field(default=None, ge=1)
    end_chapter_number: int | None = Field(default=None, ge=1)
    workflow: OrchestrationWorkflowPolicy = Field(
        default_factory=OrchestrationWorkflowPolicy
    )
    queue: OrchestrationQueuePolicy = Field(
        default_factory=OrchestrationQueuePolicy
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self) -> "NovelOrchestrationCreateRequest":
        if (
            self.start_chapter_number is not None
            and self.end_chapter_number is not None
            and self.end_chapter_number < self.start_chapter_number
        ):
            raise ValueError(
                "end_chapter_number must be greater than or equal to "
                "start_chapter_number."
            )
        if len(set(self.arc_ids)) != len(self.arc_ids):
            raise ValueError("arc_ids must not contain duplicates.")
        return self


class NovelOrchestrationControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class NovelOrchestrationRetryRequest(NovelOrchestrationControlRequest):
    reset_attempts: bool = True


class NovelOrchestrationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orchestration_id: str
    sequence_no: int = Field(ge=1)
    chapter_plan_id: str
    chapter_plan_revision: int = Field(ge=1)
    chapter_number: int = Field(ge=1)
    chapter_title: str
    arc_id: str
    arc_revision: int = Field(ge=1)
    status: NovelOrchestrationStepStatus
    workflow_run_id: str | None = None
    workflow_attempt: int = Field(default=0, ge=0)
    manuscript_chapter_id: str | None = None
    candidate_revision: int | None = Field(default=None, ge=1)
    accepted_revision: int | None = Field(default=None, ge=1)
    error: str | None = None
    created_at: str
    updated_at: str


class NovelOrchestrationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    orchestration_id: str
    sequence_no: int = Field(ge=0)
    event_type: str
    chapter_sequence_no: int | None = Field(default=None, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class NovelOrchestrationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orchestration_id: str
    novel_id: str
    user_id: str
    status: NovelOrchestrationStatus
    revision: int = Field(ge=1)
    current_sequence_no: int | None = Field(default=None, ge=1)
    total_chapters: int = Field(ge=0)
    accepted_chapters: int = Field(ge=0)
    error: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class NovelOrchestrationDetail(NovelOrchestrationSummary):
    selection: dict[str, Any] = Field(default_factory=dict)
    workflow: OrchestrationWorkflowPolicy
    queue: OrchestrationQueuePolicy
    metadata: dict[str, Any] = Field(default_factory=dict)
    paused_from_status: NovelOrchestrationStatus | None = None
    steps: list[NovelOrchestrationStep] = Field(default_factory=list)
    events: list[NovelOrchestrationEvent] = Field(default_factory=list)


class NovelOrchestrationCreateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orchestration: NovelOrchestrationDetail
    deduplicated: bool = False


class NovelOrchestrationResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelOrchestrationDetail


class NovelOrchestrationCreateResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelOrchestrationCreateResult


class NovelOrchestrationListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[NovelOrchestrationSummary] = Field(default_factory=list)
