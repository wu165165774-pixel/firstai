from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.llm.schemas import ReasoningEffort, TokenUsage


ConsistencySeverity = Literal["critical", "major", "moderate", "minor"]
ConsistencyStatus = Literal[
    "confirmed",
    "possible",
    "insufficient_evidence",
]
KnowledgeScope = Literal[
    "WORLD_TRUTH",
    "CHARACTER_KNOWLEDGE",
    "CHARACTER_BELIEF",
    "READER_KNOWLEDGE",
]
FactType = Literal[
    "relationship",
    "life_state",
    "location",
    "identity",
    "event",
]
FactChangeType = Literal["assertion", "transition"]


class ConsistencySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal[
        "novel_project",
        "story_bible",
        "canonical_entity",
        "temporal_event",
        "temporal_relation",
        "generated_text",
    ]
    source_id: str = Field(min_length=1, max_length=256)
    revision: int | None = Field(default=None, ge=1)
    excerpt: str = Field(default="", max_length=4000)


class ConsistencyConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str = Field(min_length=1, max_length=256)
    category: Literal[
        "identity",
        "world_rule",
        "relationship",
        "life_state",
        "location",
        "timeline",
        "knowledge_scope",
    ]
    severity: ConsistencySeverity
    statement: str = Field(min_length=1, max_length=8000)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    knowledge_scope: KnowledgeScope = "WORLD_TRUTH"
    knower_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    valid_from_chapter: int | None = Field(default=None, ge=1)
    valid_to_chapter: int | None = Field(default=None, ge=1)
    source: ConsistencySource


class ConsistencyFactCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fact_id: str = Field(default="", max_length=128)
    fact_type: FactType
    subject_entity_id: str | None = Field(default=None, max_length=128)
    subject_name: str | None = Field(default=None, max_length=256)
    predicate: str = Field(default="", max_length=128)
    object_entity_id: str | None = Field(default=None, max_length=128)
    object_name: str | None = Field(default=None, max_length=256)
    value: str = Field(default="", max_length=1000)
    evidence: str = Field(min_length=1, max_length=4000)
    chapter_number: int | None = Field(default=None, ge=1, le=1_000_000)
    change_type: FactChangeType = "assertion"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    knowledge_scope: KnowledgeScope = "WORLD_TRUTH"
    knowledge_holder_entity_id: str | None = Field(
        default=None,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_fact_shape(self) -> "ConsistencyFactCandidate":
        if not self.subject_entity_id and not self.subject_name:
            raise ValueError("fact subject requires entity_id or name")
        if self.fact_type in {"relationship", "location"}:
            if not self.object_entity_id and not self.object_name:
                raise ValueError(
                    f"{self.fact_type} fact requires an object entity"
                )
        if self.fact_type == "relationship" and not self.predicate:
            raise ValueError("relationship fact requires predicate")
        if self.fact_type == "life_state":
            normalized = self.value.casefold()
            if normalized not in {"alive", "dead", "存活", "死亡"}:
                raise ValueError("life_state value must be alive or dead")
        return self


class ConsistencyConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(min_length=1, max_length=128)
    conflict_type: Literal[
        "unknown_entity",
        "ambiguous_alias",
        "identity_mismatch",
        "relationship_conflict",
        "life_state_conflict",
        "location_conflict",
        "timeline_conflict",
        "unsupported_evidence",
        "knowledge_scope_violation",
    ]
    severity: ConsistencySeverity
    status: ConsistencyStatus
    blocking: bool = True
    message: str = Field(min_length=1, max_length=8000)
    expected: str = Field(default="", max_length=8000)
    generated: str = Field(default="", max_length=8000)
    recommendation: str = Field(min_length=1, max_length=8000)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    candidate_fact_id: str = Field(min_length=1, max_length=128)
    evidence: list[ConsistencySource] = Field(default_factory=list)


class ConsistencyConstraintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(min_length=1, max_length=128)
    chapter_number: int = Field(ge=1, le=1_000_000)
    active_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    pov_character_id: str | None = Field(default=None, max_length=128)
    char_budget: int = Field(default=3600, ge=512, le=12_000)


class ConsistencyCheckRequest(ConsistencyConstraintRequest):
    content: str = Field(min_length=1, max_length=80_000)
    candidate_facts: list[ConsistencyFactCandidate] = Field(
        default_factory=list,
        max_length=200,
    )


class ConsistencyAnalyzeRequest(ConsistencyConstraintRequest):
    content: str = Field(min_length=1, max_length=80_000)
    provider: str = Field(default="qwen_local", min_length=1, max_length=128)
    model: str | None = Field(default="qwen3:8b", max_length=256)
    reasoning_effort: ReasoningEffort = "medium"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1600, gt=0, le=16_000)


class ConsistencyCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    chapter_number: int
    constraints: list[ConsistencyConstraint] = Field(default_factory=list)
    candidate_facts: list[ConsistencyFactCandidate] = Field(default_factory=list)
    conflicts: list[ConsistencyConflict] = Field(default_factory=list)
    persisted: bool = False
    constraint_context: str = ""


class ConsistencyAnalyzeResult(ConsistencyCheckResult):
    provider: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    latency_ms: float | None = None


class ConsistencyConstraintResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ConsistencyCheckResult


class ConsistencyCheckResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ConsistencyCheckResult


class ConsistencyAnalyzeResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ConsistencyAnalyzeResult
