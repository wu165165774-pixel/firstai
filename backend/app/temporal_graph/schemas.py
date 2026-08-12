from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TemporalSourceType = Literal["story_bible", "accepted_manuscript"]
TemporalContextType = Literal["character", "world", "plot", "short_term"]


def _clean_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("entity ID lists must not contain blanks")
        if len(cleaned) > 128:
            raise ValueError("entity ID must not exceed 128 characters")
        if cleaned not in result:
            result.append(cleaned)
    return result


class TemporalSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: TemporalSourceType
    source_id: str = Field(min_length=1, max_length=128)
    source_revision: int = Field(ge=1)
    source_chapter_number: int | None = Field(default=None, ge=1)


class _TemporalInterval(BaseModel):
    @staticmethod
    def validate_interval(start: int, end: int | None) -> None:
        if end is not None and end < start:
            raise ValueError("temporal interval end must be >= start")


class TemporalEventCreate(_TemporalInterval):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    event_type: str = Field(min_length=1, max_length=128)
    context_type: TemporalContextType = "plot"
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(default="", max_length=12_000)
    participant_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    location_entity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    start_chapter: int = Field(ge=1, le=1_000_000)
    end_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    source: TemporalSourceReference
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("participant_entity_ids")
    @classmethod
    def clean_participants(cls, value: list[str]) -> list[str]:
        return _clean_ids(value)

    @field_validator("location_entity_id")
    @classmethod
    def clean_location(cls, value: str | None) -> str | None:
        return str(value).strip() if value is not None else None

    @model_validator(mode="after")
    def check_interval(self) -> "TemporalEventCreate":
        self.validate_interval(self.start_chapter, self.end_chapter)
        return self


class TemporalEventUpdate(_TemporalInterval):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=1)
    source: TemporalSourceReference
    event_type: str | None = Field(default=None, min_length=1, max_length=128)
    context_type: TemporalContextType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=256)
    summary: str | None = Field(default=None, max_length=12_000)
    participant_entity_ids: list[str] | None = Field(default=None, max_length=100)
    location_entity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    start_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    end_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None

    @field_validator("participant_entity_ids")
    @classmethod
    def clean_participants(cls, value: list[str] | None) -> list[str] | None:
        return _clean_ids(value) if value is not None else None


class TemporalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    novel_id: str
    event_type: str
    context_type: TemporalContextType
    title: str
    summary: str = ""
    participant_entity_ids: list[str] = Field(default_factory=list)
    location_entity_id: str | None = None
    start_chapter: int
    end_chapter: int | None = None
    source: TemporalSourceReference
    confidence: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision: int
    created_at: str
    updated_at: str


class TemporalEventRevision(BaseModel):
    event_id: str
    novel_id: str
    revision: int
    snapshot: TemporalEvent
    created_at: str


class TemporalRelationCreate(_TemporalInterval):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    relation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    subject_entity_id: str = Field(min_length=1, max_length=128)
    predicate: str = Field(min_length=1, max_length=128)
    object_entity_id: str = Field(min_length=1, max_length=128)
    context_type: TemporalContextType = "character"
    description: str = Field(default="", max_length=8000)
    valid_from_chapter: int = Field(ge=1, le=1_000_000)
    valid_to_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    source: TemporalSourceReference
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_interval(self) -> "TemporalRelationCreate":
        self.validate_interval(self.valid_from_chapter, self.valid_to_chapter)
        return self


class TemporalRelationUpdate(_TemporalInterval):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=1)
    source: TemporalSourceReference
    subject_entity_id: str | None = Field(default=None, min_length=1, max_length=128)
    predicate: str | None = Field(default=None, min_length=1, max_length=128)
    object_entity_id: str | None = Field(default=None, min_length=1, max_length=128)
    context_type: TemporalContextType | None = None
    description: str | None = Field(default=None, max_length=8000)
    valid_from_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    valid_to_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class TemporalRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_id: str
    novel_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    context_type: TemporalContextType
    description: str = ""
    valid_from_chapter: int
    valid_to_chapter: int | None = None
    source: TemporalSourceReference
    confidence: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision: int
    created_at: str
    updated_at: str


class TemporalRelationRevision(BaseModel):
    relation_id: str
    novel_id: str
    revision: int
    snapshot: TemporalRelation
    created_at: str


class TemporalGraphQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(default="", max_length=16_000)
    active_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    as_of_chapter: int | None = Field(default=None, ge=1, le=1_000_000)
    include_historical: bool = False
    context_types: list[TemporalContextType] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list, max_length=50)
    predicates: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=20, ge=1, le=100)

    @field_validator("active_entity_ids")
    @classmethod
    def clean_entities(cls, value: list[str]) -> list[str]:
        return _clean_ids(value)


class TemporalGraphEvidence(BaseModel):
    graph_id: str
    graph_kind: Literal["event", "relation"]
    context_type: TemporalContextType
    content: str
    entity_ids: list[str] = Field(default_factory=list)
    valid_from_chapter: int
    valid_to_chapter: int | None = None
    score: float
    source: TemporalSourceReference
    metadata: dict[str, Any] = Field(default_factory=dict)


class TemporalGraphQueryResult(BaseModel):
    novel_id: str
    as_of_chapter: int | None = None
    include_historical: bool
    evidence: list[TemporalGraphEvidence] = Field(default_factory=list)


class TemporalEventResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: TemporalEvent


class TemporalEventListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[TemporalEvent] = Field(default_factory=list)


class TemporalEventRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[TemporalEventRevision] = Field(default_factory=list)


class TemporalRelationResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: TemporalRelation


class TemporalRelationListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[TemporalRelation] = Field(default_factory=list)


class TemporalRelationRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[TemporalRelationRevision] = Field(default_factory=list)


class TemporalGraphQueryResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: TemporalGraphQueryResult
