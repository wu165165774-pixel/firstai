from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


NovelStatus = Literal[
    "planning",
    "writing",
    "paused",
    "completed",
    "archived",
]


class NovelProjectCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    genre: str = Field(default="", max_length=128)
    premise: str = Field(default="", max_length=8000)
    language: str = Field(default="zh-CN", min_length=1, max_length=32)
    target_word_count: int = Field(default=0, ge=0, le=100_000_000)
    status: NovelStatus = "planning"
    style_guide: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NovelProjectUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    genre: str | None = Field(default=None, max_length=128)
    premise: str | None = Field(default=None, max_length=8000)
    language: str | None = Field(default=None, min_length=1, max_length=32)
    target_word_count: int | None = Field(default=None, ge=0, le=100_000_000)
    status: NovelStatus | None = None
    style_guide: dict[str, Any] | None = None
    constraints: list[str] | None = None
    metadata: dict[str, Any] | None = None


class NovelProject(BaseModel):
    novel_id: str
    user_id: str
    title: str
    genre: str
    premise: str
    language: str
    target_word_count: int
    status: NovelStatus
    style_guide: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision: int
    story_bible_revision: int
    created_at: str
    updated_at: str


class StoryBibleUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    world: dict[str, Any] | None = None
    characters: list[dict[str, Any]] | None = None
    factions: list[dict[str, Any]] | None = None
    locations: list[dict[str, Any]] | None = None
    rules: list[dict[str, Any]] | None = None
    themes: list[str] | None = None
    timeline: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class StoryBible(BaseModel):
    novel_id: str
    revision: int
    world: dict[str, Any] = Field(default_factory=dict)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    factions: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str


class StoryBibleRevision(BaseModel):
    novel_id: str
    revision: int
    snapshot: StoryBible
    created_at: str


class NovelPlanPlotBeat(BaseModel):
    beat_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=1, le=100_000)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=8000)
    purpose: str = Field(default="", max_length=4000)
    character_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NovelPlanCharacterArc(BaseModel):
    character_id: str = Field(min_length=1, max_length=128)
    character_name: str = Field(default="", max_length=256)
    role: str = Field(default="", max_length=128)
    start_state: str = Field(default="", max_length=8000)
    desire: str = Field(default="", max_length=4000)
    need: str = Field(default="", max_length=4000)
    internal_conflict: str = Field(default="", max_length=8000)
    external_conflict: str = Field(default="", max_length=8000)
    midpoint_shift: str = Field(default="", max_length=8000)
    end_state: str = Field(default="", max_length=8000)
    key_turning_points: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NovelPlanVolume(BaseModel):
    volume_number: int = Field(ge=1, le=10_000)
    title: str = Field(default="", max_length=256)
    purpose: str = Field(default="", max_length=8000)
    start_state: str = Field(default="", max_length=8000)
    end_state: str = Field(default="", max_length=8000)
    core_conflict: str = Field(default="", max_length=8000)
    climax: str = Field(default="", max_length=8000)
    target_word_count: int = Field(default=0, ge=0, le=100_000_000)
    major_events: list[str] = Field(default_factory=list)
    character_focus: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NovelPlanUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    story_premise: str | None = Field(default=None, max_length=12000)
    core_conflict: str | None = Field(default=None, max_length=12000)
    central_question: str | None = Field(default=None, max_length=8000)
    ending_direction: str | None = Field(default=None, max_length=12000)
    themes: list[str] | None = None
    main_plot: list[NovelPlanPlotBeat] | None = None
    character_arcs: list[NovelPlanCharacterArc] | None = None
    volume_plans: list[NovelPlanVolume] | None = None
    metadata: dict[str, Any] | None = None


class NovelPlan(BaseModel):
    novel_id: str
    revision: int
    source_project_revision: int
    source_story_bible_revision: int
    is_stale: bool = False
    story_premise: str = ""
    core_conflict: str = ""
    central_question: str = ""
    ending_direction: str = ""
    themes: list[str] = Field(default_factory=list)
    main_plot: list[NovelPlanPlotBeat] = Field(default_factory=list)
    character_arcs: list[NovelPlanCharacterArc] = Field(default_factory=list)
    volume_plans: list[NovelPlanVolume] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class NovelPlanRevision(BaseModel):
    novel_id: str
    revision: int
    snapshot: NovelPlan
    created_at: str


class StoryArcTurningPoint(BaseModel):
    turning_point_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=1, le=100_000)
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8000)
    consequence: str = Field(default="", max_length=8000)
    character_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoryArcCharacterProgression(BaseModel):
    character_id: str = Field(min_length=1, max_length=128)
    character_name: str = Field(default="", max_length=256)
    start_state: str = Field(default="", max_length=8000)
    change: str = Field(default="", max_length=8000)
    end_state: str = Field(default="", max_length=8000)
    key_moments: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoryArcCreate(BaseModel):
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


class StoryArcUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    volume_number: int | None = Field(default=None, ge=1, le=10_000)
    arc_number: int | None = Field(default=None, ge=1, le=100_000)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    objective: str | None = Field(default=None, max_length=8000)
    summary: str | None = Field(default=None, max_length=12000)
    opening_state: str | None = Field(default=None, max_length=8000)
    closing_state: str | None = Field(default=None, max_length=8000)
    core_conflict: str | None = Field(default=None, max_length=12000)
    stakes: str | None = Field(default=None, max_length=8000)
    turning_points: list[StoryArcTurningPoint] | None = None
    character_progression: list[StoryArcCharacterProgression] | None = None
    plot_threads: list[str] | None = None
    dependencies: list[str] | None = None
    target_chapter_start: int | None = Field(default=None, ge=1, le=1_000_000)
    target_chapter_end: int | None = Field(default=None, ge=1, le=1_000_000)
    metadata: dict[str, Any] | None = None


class StoryArc(BaseModel):
    arc_id: str
    novel_id: str
    volume_number: int
    arc_number: int
    revision: int
    source_project_revision: int
    source_story_bible_revision: int
    source_novel_plan_revision: int
    is_stale: bool = False
    title: str
    objective: str = ""
    summary: str = ""
    opening_state: str = ""
    closing_state: str = ""
    core_conflict: str = ""
    stakes: str = ""
    turning_points: list[StoryArcTurningPoint] = Field(default_factory=list)
    character_progression: list[StoryArcCharacterProgression] = Field(default_factory=list)
    plot_threads: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    target_chapter_start: int | None = None
    target_chapter_end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class StoryArcRevision(BaseModel):
    arc_id: str
    novel_id: str
    revision: int
    snapshot: StoryArc
    created_at: str


class NovelProjectResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelProject


class NovelProjectListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[NovelProject] = Field(default_factory=list)


class StoryBibleResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: StoryBible


class StoryBibleRevisionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: StoryBibleRevision


class StoryBibleRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[StoryBibleRevision] = Field(default_factory=list)


class NovelPlanResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelPlan


class NovelPlanRevisionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelPlanRevision


class NovelPlanRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[NovelPlanRevision] = Field(default_factory=list)

class StoryArcResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: StoryArc


class StoryArcListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[StoryArc] = Field(default_factory=list)


class StoryArcRevisionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: StoryArcRevision


class StoryArcRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[StoryArcRevision] = Field(default_factory=list)
