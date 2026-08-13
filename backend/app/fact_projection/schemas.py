from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FactProjectionStatus = Literal[
    "pending",
    "processing",
    "completed",
    "failed",
]
FactProjectionOperation = Literal["project", "retract"]
FactProjectionOverallStatus = Literal[
    "pending",
    "processing",
    "completed",
    "failed",
]


class FactProjectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_id: str
    novel_id: str
    manuscript_chapter_id: str
    manuscript_revision: int
    chapter_number: int
    fact_index: int
    fact_id: str
    operation: FactProjectionOperation = "project"
    superseded_by_revision: int | None = None
    status: FactProjectionStatus
    attempts: int = 0
    memory_id: str | None = None
    memory_projected: bool = False
    vector_projected: bool = False
    graph_kind: Literal["event", "relation"] | None = None
    graph_id: str | None = None
    graph_projected: bool = False
    last_error: str = ""
    created_at: str
    updated_at: str
    completed_at: str | None = None


class FactProjectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    manuscript_chapter_id: str
    manuscript_revision: int
    status: FactProjectionOverallStatus
    total_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    processing_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    items: list[FactProjectionItem] = Field(default_factory=list)


class FactProjectionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: FactProjectionSummary
