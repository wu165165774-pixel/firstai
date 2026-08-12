from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetrievalPath(str, Enum):
    VECTOR = "vector"
    GRAPH = "graph"


class RetrievalLaneStatus(str, Enum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class DualRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(min_length=1, max_length=128)
    novel_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=16_000)
    top_k: int = Field(default=6, ge=1, le=20)
    char_budget: int = Field(default=2400, ge=256, le=12_000)
    min_vector_similarity: float = Field(default=0.35, ge=-1.0, le=1.0)
    timeout_ms: int = Field(default=5000, ge=50, le=30_000)
    allowed_memory_types: list[str] = Field(default_factory=list, max_length=20)
    active_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    as_of: str | None = Field(default=None, max_length=128)

    @field_validator("allowed_memory_types", "active_entity_ids")
    @classmethod
    def normalize_string_list(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = str(item or "").strip()
            if not normalized:
                raise ValueError("Retrieval filter lists must not contain blanks.")
            if len(normalized) > 128:
                raise ValueError("Retrieval filter value exceeds 128 characters.")
            if normalized not in result:
                result.append(normalized)
        return result


class RetrievalSourceReference(BaseModel):
    path: RetrievalPath
    source_id: str
    rank: int = Field(ge=1)
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class FusedRetrievalEvidence(BaseModel):
    evidence_id: str
    content: str
    evidence_type: str
    source_paths: list[RetrievalPath]
    sources: list[RetrievalSourceReference]
    fusion_score: float
    truncated: bool = False


class RetrievalLaneDiagnostic(BaseModel):
    path: RetrievalPath
    status: RetrievalLaneStatus
    latency_ms: float = Field(ge=0)
    candidate_count: int = Field(ge=0)
    error: str | None = None


class DualRetrievalResult(BaseModel):
    mode: Literal["dual", "vector_only", "graph_only", "unavailable"]
    degraded: bool
    evidence: list[FusedRetrievalEvidence] = Field(default_factory=list)
    lanes: list[RetrievalLaneDiagnostic]
    char_budget: int
    chars_used: int
    truncated: bool
    deduplicated_count: int = Field(ge=0)

