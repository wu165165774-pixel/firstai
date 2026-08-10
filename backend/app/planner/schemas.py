from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.llm.schemas import TokenUsage
from app.novels.schemas import (
    ChapterPlan,
    ChapterPlanSceneBeat,
    NovelPlan,
    NovelPlanCharacterArc,
    NovelPlanPlotBeat,
    NovelPlanVolume,
    StoryArc,
    StoryArcCharacterProgression,
    StoryArcTurningPoint,
)


PlannerTarget = Literal[
    "novel_plan",
    "story_arc",
    "chapter_plan",
]

PlannerReasoningEffort = Literal[
    "none",
    "low",
    "medium",
    "high",
]


class NovelPlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_premise: str = Field(default="", max_length=12000)
    core_conflict: str = Field(default="", max_length=12000)
    central_question: str = Field(default="", max_length=8000)
    ending_direction: str = Field(default="", max_length=12000)
    themes: list[str] = Field(default_factory=list)
    main_plot: list[NovelPlanPlotBeat] = Field(default_factory=list)
    character_arcs: list[NovelPlanCharacterArc] = Field(default_factory=list)
    volume_plans: list[NovelPlanVolume] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoryArcCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volume_number: int = Field(ge=1, le=10_000)
    arc_number: int = Field(ge=1, le=100_000)
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(default="", max_length=8000)
    summary: str = Field(default="", max_length=12000)
    opening_state: str = Field(default="", max_length=8000)
    closing_state: str = Field(default="", max_length=8000)
    core_conflict: str = Field(default="", max_length=12000)
    stakes: str = Field(default="", max_length=8000)
    turning_points: list[StoryArcTurningPoint] = Field(default_factory=list)
    character_progression: list[StoryArcCharacterProgression] = Field(default_factory=list)
    plot_threads: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    target_chapter_start: int | None = Field(default=None, ge=1, le=1_000_000)
    target_chapter_end: int | None = Field(default=None, ge=1, le=1_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChapterPlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arc_id: str = Field(min_length=1, max_length=128)
    chapter_number: int = Field(ge=1, le=1_000_000)
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(default="", max_length=8000)
    summary: str = Field(default="", max_length=12000)
    pov_character_id: str | None = Field(default=None, max_length=128)
    pov_character_name: str = Field(default="", max_length=256)
    opening_state: str = Field(default="", max_length=8000)
    closing_state: str = Field(default="", max_length=8000)
    conflict: str = Field(default="", max_length=12000)
    reveal: str = Field(default="", max_length=8000)
    hook: str = Field(default="", max_length=8000)
    scene_beats: list[ChapterPlanSceneBeat] = Field(default_factory=list)
    continuity_dependencies: list[str] = Field(default_factory=list)
    target_word_count: int = Field(default=0, ge=0, le=1_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


PlannerCandidate = (
    NovelPlanCandidate
    | StoryArcCandidate
    | ChapterPlanCandidate
)


class PlannerGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: PlannerTarget
    instruction: str = Field(min_length=1, max_length=16000)

    provider: str = Field(default="qwen_local", min_length=1, max_length=128)
    model: str | None = Field(default="qwen3:8b", max_length=256)
    use_memory: bool = True
    reasoning_effort: PlannerReasoningEffort = "medium"
    temperature: float | None = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=2600, gt=0, le=32000)

    volume_number: int | None = Field(default=None, ge=1, le=10_000)
    arc_number: int | None = Field(default=None, ge=1, le=100_000)
    arc_id: str | None = Field(default=None, min_length=1, max_length=128)
    chapter_number: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_target_coordinates(self) -> "PlannerGenerateRequest":
        if self.target == "story_arc":
            if self.volume_number is None or self.arc_number is None:
                raise ValueError(
                    "story_arc target requires volume_number and arc_number"
                )

        if self.target == "chapter_plan":
            if self.arc_id is None or self.chapter_number is None:
                raise ValueError(
                    "chapter_plan target requires arc_id and chapter_number"
                )

        return self


class PlannerSourceRevisions(BaseModel):
    project_revision: int
    story_bible_revision: int
    novel_plan_revision: int
    story_arc_revision: int | None = None


class PlannerGenerateResult(BaseModel):
    target: PlannerTarget
    candidate: PlannerCandidate
    source_revisions: PlannerSourceRevisions

    provider: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    persisted: bool = False


class PlannerGenerateResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: PlannerGenerateResult


class PlannerAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: PlannerTarget
    candidate: PlannerCandidate
    source_revisions: PlannerSourceRevisions

    volume_number: int | None = Field(default=None, ge=1, le=10_000)
    arc_number: int | None = Field(default=None, ge=1, le=100_000)
    arc_id: str | None = Field(default=None, min_length=1, max_length=128)
    chapter_number: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_target_candidate(self) -> "PlannerAcceptRequest":
        candidate_types = {
            "novel_plan": NovelPlanCandidate,
            "story_arc": StoryArcCandidate,
            "chapter_plan": ChapterPlanCandidate,
        }
        expected_type = candidate_types[self.target]

        if not isinstance(self.candidate, expected_type):
            raise ValueError(
                f"{self.target} target requires "
                f"{expected_type.__name__}"
            )

        if self.target == "story_arc":
            if self.volume_number is None or self.arc_number is None:
                raise ValueError(
                    "story_arc target requires volume_number and arc_number"
                )
            assert isinstance(self.candidate, StoryArcCandidate)
            if (
                self.candidate.volume_number != self.volume_number
                or self.candidate.arc_number != self.arc_number
            ):
                raise ValueError(
                    "Story Arc candidate does not match fixed coordinates"
                )

        if self.target == "chapter_plan":
            if self.arc_id is None or self.chapter_number is None:
                raise ValueError(
                    "chapter_plan target requires arc_id and chapter_number"
                )
            assert isinstance(self.candidate, ChapterPlanCandidate)
            if (
                self.candidate.arc_id != self.arc_id
                or self.candidate.chapter_number != self.chapter_number
            ):
                raise ValueError(
                    "Chapter Plan candidate does not match fixed coordinates"
                )
            if self.source_revisions.story_arc_revision is None:
                raise ValueError(
                    "chapter_plan acceptance requires story_arc_revision"
                )

        if (
            self.target != "chapter_plan"
            and self.source_revisions.story_arc_revision is not None
        ):
            raise ValueError(
                "story_arc_revision is only valid for chapter_plan"
            )

        return self


class PlannerAcceptResult(BaseModel):
    target: PlannerTarget
    source_revisions: PlannerSourceRevisions
    persisted: Literal[True] = True

    novel_plan: NovelPlan | None = None
    story_arc: StoryArc | None = None
    chapter_plan: ChapterPlan | None = None

    @model_validator(mode="after")
    def validate_accepted_entity(self) -> "PlannerAcceptResult":
        entities = {
            "novel_plan": self.novel_plan,
            "story_arc": self.story_arc,
            "chapter_plan": self.chapter_plan,
        }
        present = [
            target
            for target, entity in entities.items()
            if entity is not None
        ]

        if present != [self.target]:
            raise ValueError(
                "accepted entity must match target exactly"
            )

        return self


class PlannerAcceptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: PlannerAcceptResult
