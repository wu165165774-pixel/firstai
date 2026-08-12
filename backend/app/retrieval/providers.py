from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.memory.hybrid_retriever import hybrid_memory_retriever
from app.memory.schemas import MemoryTier

from .schemas import DualRetrievalRequest, RetrievalPath


class RetrievalPathUnavailable(RuntimeError):
    """The retrieval lane has no configured runtime provider."""


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    path: RetrievalPath
    source_id: str
    content: str
    evidence_type: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalProvider(Protocol):
    path: RetrievalPath

    async def retrieve(
        self,
        request: DualRetrievalRequest,
        candidate_k: int,
    ) -> list[RetrievalCandidate]: ...


class VectorMemoryRetrievalProvider:
    path = RetrievalPath.VECTOR

    async def retrieve(
        self,
        request: DualRetrievalRequest,
        candidate_k: int,
    ) -> list[RetrievalCandidate]:
        allowed_types = set(request.allowed_memory_types)
        raw = await hybrid_memory_retriever.retrieve(
            user_id=request.user_id,
            novel_id=request.novel_id,
            query=request.query,
            top_k=min(max(candidate_k * 3, candidate_k), 60),
            min_similarity=request.min_vector_similarity,
            memory_tiers={
                MemoryTier.WORKING.value,
                MemoryTier.LONG_TERM.value,
            },
        )

        result: list[RetrievalCandidate] = []
        for index, item in enumerate(raw):
            evidence_type = str(
                getattr(item, "memory_type", "memory") or "memory"
            )
            if allowed_types and evidence_type not in allowed_types:
                continue
            content = str(getattr(item, "content", "") or "").strip()
            if not content:
                continue
            source_id = str(
                getattr(item, "memory_id", "") or f"vector-rank-{index + 1}"
            )
            result.append(
                RetrievalCandidate(
                    path=self.path,
                    source_id=source_id,
                    content=content,
                    evidence_type=evidence_type,
                    score=float(
                        getattr(
                            item,
                            "hybrid_score",
                            getattr(item, "similarity", 0.0),
                        )
                        or 0.0
                    ),
                    metadata={
                        "memory_tier": str(
                            getattr(item, "memory_tier", "long_term")
                            or "long_term"
                        ),
                        "similarity": float(
                            getattr(item, "similarity", 0.0) or 0.0
                        ),
                        "importance": float(
                            getattr(item, "importance", 0.0) or 0.0
                        ),
                    },
                )
            )
            if len(result) >= candidate_k:
                break
        return result


class UnavailableTemporalGraphProvider:
    """Explicit placeholder until Sprint 08D.1 supplies graph storage."""

    path = RetrievalPath.GRAPH

    async def retrieve(
        self,
        request: DualRetrievalRequest,
        candidate_k: int,
    ) -> list[RetrievalCandidate]:
        del request, candidate_k
        raise RetrievalPathUnavailable(
            "Temporal Graph provider is not configured (planned for Sprint 08D.1)."
        )

