from __future__ import annotations

import asyncio

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.memory.hybrid_retriever import hybrid_memory_retriever
from app.memory.schemas import MemoryTier
from app.novels.storage import NovelProjectNotFoundError
from app.temporal_graph.schemas import TemporalGraphQueryRequest
from app.temporal_graph.service import temporal_graph_service

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


class TemporalGraphRetrievalProvider:
    """Retrieve chapter-valid event/relation evidence from Temporal Graph."""

    path = RetrievalPath.GRAPH

    @staticmethod
    def _as_of_chapter(value: str | None) -> int | None:
        if value is None:
            return None
        normalized = str(value).strip().casefold()
        if not normalized:
            return None
        if normalized.isdigit():
            return int(normalized)
        for prefix in ("chapter:", "chapter-", "chapter#"):
            if normalized.startswith(prefix):
                suffix = normalized[len(prefix) :].strip()
                if suffix.isdigit():
                    return int(suffix)
        raise ValueError("as_of must be a chapter number")

    async def retrieve(
        self,
        request: DualRetrievalRequest,
        candidate_k: int,
    ) -> list[RetrievalCandidate]:
        contexts = [
            item
            for item in request.allowed_memory_types
            if item in {"character", "world", "plot", "short_term"}
        ]
        try:
            result = await asyncio.to_thread(
                temporal_graph_service.query,
                request.novel_id,
                TemporalGraphQueryRequest(
                    query=request.query,
                    active_entity_ids=request.active_entity_ids,
                    as_of_chapter=self._as_of_chapter(request.as_of),
                    include_historical=False,
                    context_types=contexts,
                    top_k=min(candidate_k, 100),
                ),
                expected_user_id=request.user_id,
            )
        except NovelProjectNotFoundError as exc:
            raise RetrievalPathUnavailable(
                "Temporal Graph scope is unavailable"
            ) from exc
        return [
            RetrievalCandidate(
                path=self.path,
                source_id=item.graph_id,
                content=item.content,
                evidence_type=item.context_type,
                score=item.score,
                metadata={
                    "graph_kind": item.graph_kind,
                    "entity_ids": item.entity_ids,
                    "valid_from_chapter": item.valid_from_chapter,
                    "valid_to_chapter": item.valid_to_chapter,
                    "source": item.source.model_dump(mode="json"),
                    **item.metadata,
                },
            )
            for item in result.evidence
        ]
