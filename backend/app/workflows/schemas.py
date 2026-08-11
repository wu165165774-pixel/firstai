from __future__ import annotations

from typing import (
    Any,
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.llm.schemas import ReasoningEffort


ReviewSeverity = Literal[
    "critical",
    "major",
    "moderate",
    "minor",
]

TrackedIssueStatus = Literal[
    "open",
    "resolved",
]

IssueTransitionType = Literal[
    "new",
    "persisting",
    "resolved",
    "reopened",
]

WorkflowStatus = Literal[
    "completed",
    "draft_failed",
    "review_failed",
    "review_parse_failed",
    "rewrite_failed",
    "stagnation_detected",
    "max_revisions_reached",
]


class ReviewScores(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    continuity: float = Field(
        ge=0.0,
        le=100.0,
    )

    character_consistency: float = Field(
        ge=0.0,
        le=100.0,
    )

    world_consistency: float = Field(
        ge=0.0,
        le=100.0,
    )

    plot_logic: float = Field(
        ge=0.0,
        le=100.0,
    )

    prose_quality: float = Field(
        ge=0.0,
        le=100.0,
    )

    pacing: float = Field(
        ge=0.0,
        le=100.0,
    )

    overall: float = Field(
        ge=0.0,
        le=100.0,
    )


class ReviewIssue(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    issue_id: str = ""

    severity: ReviewSeverity

    category: str = Field(
        min_length=1
    )

    issue: str = Field(
        min_length=1
    )

    evidence: str = Field(
        min_length=1
    )

    impact: str = Field(
        min_length=1
    )

    recommendation: str = Field(
        min_length=1
    )


class ReviewReport(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    approved: bool

    summary: str = Field(
        min_length=1
    )

    scores: ReviewScores

    issues: list[ReviewIssue] = Field(
        default_factory=list
    )

    scores_inferred: bool = False

    scores_normalized: bool = False


class TrackedIssue(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    issue_id: str = Field(
        min_length=1
    )

    status: TrackedIssueStatus

    first_seen_round: int = Field(
        ge=1
    )

    last_seen_round: int = Field(
        ge=1
    )

    severity: ReviewSeverity

    category: str

    issue: str

    evidence: str

    impact: str

    recommendation: str

    resolution_note: str = ""


class IssueTransition(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    issue_id: str

    round_index: int = Field(
        ge=1
    )

    transition: IssueTransitionType

    note: str = ""


class RevisionDiffSummary(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    round_index: int = Field(
        ge=1
    )

    changed: bool

    before_length: int = Field(
        ge=0
    )

    after_length: int = Field(
        ge=0
    )

    added_characters: int = Field(
        ge=0
    )

    removed_characters: int = Field(
        ge=0
    )

    replaced_characters: int = Field(
        ge=0
    )

    similarity_ratio: float = Field(
        ge=0.0,
        le=1.0,
    )

    summary: str


class WorkflowStep(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    stage: Literal[
        "draft",
        "review",
        "rewrite",
    ]

    round_index: int = Field(
        default=0,
        ge=0,
    )

    attempt_index: int = Field(
        default=1,
        ge=1,
    )

    agent: str

    success: bool

    content: str

    provider: str = ""

    model: str = ""

    finish_reason: str | None = None

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    latency_ms: float = 0.0

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class WorkflowUsage(BaseModel):

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    latency_ms: float = 0.0


class ChapterWorkflowRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "required": [
                "user_id",
                "novel_id",
                "instruction",
                "chapter_plan_id",
                "chapter_plan_revision",
            ]
        },
    )

    user_id: str = Field(
        min_length=1
    )

    novel_id: str = Field(
        min_length=1
    )

    instruction: str = Field(
        min_length=1
    )

    # Optional in the Python model only so persisted runs created
    # before Sprint 08B.1 remain readable and resumable as records.
    # All HTTP entry points for new workflow execution require both
    # fields and ChapterWorkflow grounds them before any Agent call.
    chapter_plan_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    chapter_plan_revision: int | None = Field(
        default=None,
        ge=1,
    )

    provider: str = "qwen_local"

    model: str | None = None

    use_memory: bool = True

    auto_rewrite: bool = True

    max_revision_rounds: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    review_retry_attempts: int = Field(
        default=1,
        ge=0,
        le=2,
    )

    review_retry_reasoning_effort: ReasoningEffort = (
        "none"
    )

    minimum_overall_score: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
    )

    minimum_dimension_score: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
    )

    require_all_issues_resolved: bool = True

    chapter_reasoning_effort: ReasoningEffort = (
        "low"
    )

    review_reasoning_effort: ReasoningEffort = (
        "medium"
    )

    rewrite_reasoning_effort: ReasoningEffort = (
        "none"
    )

    chapter_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
    )

    review_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
    )

    rewrite_temperature: float = Field(
        default=0.5,
        ge=0.0,
        le=2.0,
    )

    chapter_max_tokens: int = Field(
        default=1600,
        gt=0,
    )

    review_max_tokens: int = Field(
        default=1200,
        gt=0,
    )

    rewrite_max_tokens: int = Field(
        default=1600,
        gt=0,
    )

    rewrite_on_severities: list[
        ReviewSeverity
    ] = Field(
        default_factory=lambda: [
            "critical",
            "major",
        ]
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_chapter_plan_binding(
        self,
    ) -> "ChapterWorkflowRequest":
        if (
            self.chapter_plan_id is None
        ) != (
            self.chapter_plan_revision is None
        ):
            raise ValueError(
                "chapter_plan_id and chapter_plan_revision "
                "must be supplied together."
            )
        return self


class ChapterWorkflowResult(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    status: WorkflowStatus

    draft: str = ""

    review_report: ReviewReport | None = None

    review_history: list[ReviewReport] = Field(
        default_factory=list
    )

    review_raw: str = ""

    review_raw_history: list[str] = Field(
        default_factory=list
    )

    quality_scores: ReviewScores | None = None

    quality_score_history: list[
        ReviewScores
    ] = Field(
        default_factory=list
    )

    issue_tracker: list[TrackedIssue] = Field(
        default_factory=list
    )

    issue_transitions: list[
        IssueTransition
    ] = Field(
        default_factory=list
    )

    unresolved_issue_ids: list[str] = Field(
        default_factory=list
    )

    quality_gate_reasons: list[str] = Field(
        default_factory=list
    )

    revision_diffs: list[
        RevisionDiffSummary
    ] = Field(
        default_factory=list
    )

    final_content: str = ""

    revision_applied: bool = False

    revision_rounds: int = 0

    quality_gate_passed: bool = False

    workflow_steps: list[WorkflowStep] = Field(
        default_factory=list
    )

    usage: WorkflowUsage = Field(
        default_factory=WorkflowUsage
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class ChapterWorkflowResponse(BaseModel):

    code: int = 0

    message: str = "success"

    data: ChapterWorkflowResult
