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

from app.llm.schemas import (
    ReasoningEffort,
)


ReviewSeverity = Literal[
    "critical",
    "major",
    "moderate",
    "minor",
]

WorkflowStatus = Literal[
    "completed",
    "draft_failed",
    "review_failed",
    "review_parse_failed",
    "rewrite_failed",
]


class ReviewIssue(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

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

    issues: list[ReviewIssue] = Field(
        default_factory=list
    )


class WorkflowStep(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    stage: Literal[
        "draft",
        "review",
        "rewrite",
    ]

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
        extra="forbid"
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

    provider: str = "qwen_local"

    model: str | None = None

    use_memory: bool = True

    auto_rewrite: bool = True

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


class ChapterWorkflowResult(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    status: WorkflowStatus

    draft: str = ""

    review_report: ReviewReport | None = None

    review_raw: str = ""

    final_content: str = ""

    revision_applied: bool = False

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
