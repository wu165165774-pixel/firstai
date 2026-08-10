from __future__ import annotations

import unicodedata

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


NovelStatus = Literal[
    "planning",
    "writing",
    "paused",
    "completed",
    "archived",
]

EntityType = Literal[
    "character",
    "organization",
    "location",
    "item",
    "creature",
    "concept",
]

EntityResolutionStatus = Literal[
    "resolved",
    "ambiguous",
    "not_found",
]

EntityResolutionStrategy = Literal[
    "exact_canonical",
    "exact_alias",
    "normalized_canonical",
    "normalized_alias",
]


def clean_entity_name(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_entity_name(value: Any) -> str:
    cleaned = clean_entity_name(value)
    return unicodedata.normalize(
        "NFKC",
        cleaned,
    ).casefold()


def clean_entity_aliases(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = clean_entity_name(value)
        if not cleaned:
            raise ValueError("aliases must not contain blank names")
        if len(cleaned) > 256:
            raise ValueError("alias must not exceed 256 characters")

        normalized = normalize_entity_name(cleaned)
        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(cleaned)

    return result


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


class NovelEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    entity_type: EntityType = "character"
    canonical_name: str = Field(min_length=1, max_length=256)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    description: str = Field(default="", max_length=8000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_id")
    @classmethod
    def clean_entity_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("canonical_name")
    @classmethod
    def clean_canonical_name(cls, value: str) -> str:
        cleaned = clean_entity_name(value)
        if not cleaned:
            raise ValueError("canonical_name must not be blank")
        return cleaned

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str]) -> list[str]:
        return clean_entity_aliases(values)


class NovelEntityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)
    canonical_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    aliases: list[str] | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=8000)
    metadata: dict[str, Any] | None = None

    @field_validator("canonical_name")
    @classmethod
    def clean_canonical_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_entity_name(value)
        if not cleaned:
            raise ValueError("canonical_name must not be blank")
        return cleaned

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return clean_entity_aliases(values)


class NovelEntity(BaseModel):
    entity_id: str
    novel_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    revision: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class EntityResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    entity_type: EntityType | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = clean_entity_name(value)
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class EntityResolution(BaseModel):
    query: str
    normalized_query: str
    status: EntityResolutionStatus
    match_strategy: EntityResolutionStrategy | None = None
    entity: NovelEntity | None = None
    candidates: list[NovelEntity] = Field(default_factory=list)


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


class ChapterPlanSceneBeat(BaseModel):
    beat_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=1, le=100_000)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=8000)
    purpose: str = Field(default="", max_length=4000)
    character_ids: list[str] = Field(default_factory=list)
    location_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChapterPlanCreate(BaseModel):
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


class ChapterPlanUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    arc_id: str | None = Field(default=None, min_length=1, max_length=128)
    chapter_number: int | None = Field(default=None, ge=1, le=1_000_000)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    objective: str | None = Field(default=None, max_length=8000)
    summary: str | None = Field(default=None, max_length=12000)
    pov_character_id: str | None = Field(default=None, max_length=128)
    pov_character_name: str | None = Field(default=None, max_length=256)
    opening_state: str | None = Field(default=None, max_length=8000)
    closing_state: str | None = Field(default=None, max_length=8000)
    conflict: str | None = Field(default=None, max_length=12000)
    reveal: str | None = Field(default=None, max_length=8000)
    hook: str | None = Field(default=None, max_length=8000)
    scene_beats: list[ChapterPlanSceneBeat] | None = None
    continuity_dependencies: list[str] | None = None
    target_word_count: int | None = Field(default=None, ge=0, le=1_000_000)
    metadata: dict[str, Any] | None = None


class ChapterPlan(BaseModel):
    chapter_plan_id: str
    novel_id: str
    arc_id: str
    volume_number: int
    arc_number: int
    chapter_number: int
    revision: int
    source_project_revision: int
    source_story_bible_revision: int
    source_novel_plan_revision: int
    source_story_arc_revision: int
    is_stale: bool = False
    title: str
    objective: str = ""
    summary: str = ""
    pov_character_id: str | None = None
    pov_character_name: str = ""
    opening_state: str = ""
    closing_state: str = ""
    conflict: str = ""
    reveal: str = ""
    hook: str = ""
    scene_beats: list[ChapterPlanSceneBeat] = Field(default_factory=list)
    continuity_dependencies: list[str] = Field(default_factory=list)
    target_word_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ChapterPlanRevision(BaseModel):
    chapter_plan_id: str
    novel_id: str
    revision: int
    snapshot: ChapterPlan
    created_at: str


class NovelProjectResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelProject


class NovelEntityResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelEntity


class NovelEntityListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[NovelEntity] = Field(default_factory=list)


class EntityResolutionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: EntityResolution


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

class ChapterPlanResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ChapterPlan


class ChapterPlanListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[ChapterPlan] = Field(default_factory=list)


class ChapterPlanRevisionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ChapterPlanRevision


class ChapterPlanRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[ChapterPlanRevision] = Field(default_factory=list)
