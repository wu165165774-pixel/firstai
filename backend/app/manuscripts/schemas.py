from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.consistency.schemas import ConsistencyFactCandidate
from app.fact_projection.schemas import FactProjectionSummary


ManuscriptSourceStage = Literal[
    "draft",
    "rewrite",
    "checkpoint",
]
ManuscriptReviewStatus = Literal[
    "superseded",
    "approved",
]


class ManuscriptImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str = Field(min_length=1, max_length=128)
    expected_manuscript_revision: int | None = Field(
        default=None,
        ge=1,
    )


class ManuscriptAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_manuscript_revision: int = Field(ge=1)


class ManuscriptChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manuscript_chapter_id: str
    novel_id: str
    chapter_number: int
    chapter_plan_id: str
    revision: int
    latest_revision: int
    accepted_revision: int | None = None
    accepted_at: str | None = None
    created_at: str
    updated_at: str


class ManuscriptRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manuscript_chapter_id: str
    novel_id: str
    revision: int
    content: str
    content_hash: str
    source_workflow_run_id: str
    source_workflow_version_id: str
    source_stage: ManuscriptSourceStage
    source_round_index: int
    review_status: ManuscriptReviewStatus
    quality_scores: dict[str, Any] = Field(default_factory=dict)
    review_summary: str = ""
    source_project_revision: int
    source_story_bible_revision: int
    source_novel_plan_revision: int
    source_story_arc_id: str
    source_story_arc_revision: int
    source_chapter_plan_id: str
    source_chapter_plan_revision: int
    candidate_facts: list[ConsistencyFactCandidate] = Field(
        default_factory=list,
        max_length=200,
    )
    is_accepted: bool = False
    created_at: str


class ManuscriptChapterDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: ManuscriptChapter
    latest: ManuscriptRevision | None = None
    accepted: ManuscriptRevision | None = None


class ManuscriptImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: ManuscriptChapter
    imported_revisions: list[ManuscriptRevision] = Field(
        default_factory=list
    )
    deduplicated: bool = False


class ManuscriptAcceptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: ManuscriptChapter
    accepted_revision: ManuscriptRevision
    changed: bool = True
    fact_projection: FactProjectionSummary | None = None


class ManuscriptChapterResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ManuscriptChapterDetail


class ManuscriptChapterListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[ManuscriptChapter] = Field(default_factory=list)


class ManuscriptRevisionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ManuscriptRevision


class ManuscriptRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[ManuscriptRevision] = Field(default_factory=list)


class ManuscriptImportResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ManuscriptImportResult


class ManuscriptAcceptResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ManuscriptAcceptResult
