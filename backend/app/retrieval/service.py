from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from time import perf_counter

from .providers import (
    RetrievalCandidate,
    RetrievalPathUnavailable,
    RetrievalProvider,
    TemporalGraphRetrievalProvider,
    VectorMemoryRetrievalProvider,
)
from .schemas import (
    DualRetrievalRequest,
    DualRetrievalResult,
    FusedRetrievalEvidence,
    RetrievalLaneDiagnostic,
    RetrievalLaneStatus,
    RetrievalPath,
    RetrievalSourceReference,
)


@dataclass(slots=True)
class _LaneOutcome:
    path: RetrievalPath
    status: RetrievalLaneStatus
    candidates: list[RetrievalCandidate]
    latency_ms: float
    error: str | None = None


class DualPathRetriever:
    """Run Vector and Graph lanes concurrently, then fuse deterministically."""

    RRF_K = 60

    def __init__(
        self,
        vector_provider: RetrievalProvider | None = None,
        graph_provider: RetrievalProvider | None = None,
    ) -> None:
        self.vector_provider = vector_provider or VectorMemoryRetrievalProvider()
        self.graph_provider = graph_provider or TemporalGraphRetrievalProvider()

    @staticmethod
    def _fingerprint(content: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(content or ""))
        normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def _run_lane(
        self,
        provider: RetrievalProvider,
        request: DualRetrievalRequest,
        candidate_k: int,
    ) -> _LaneOutcome:
        started = perf_counter()
        try:
            candidates = await asyncio.wait_for(
                provider.retrieve(request, candidate_k),
                timeout=request.timeout_ms / 1000,
            )
            return _LaneOutcome(
                path=provider.path,
                status=RetrievalLaneStatus.SUCCESS,
                candidates=list(candidates),
                latency_ms=(perf_counter() - started) * 1000,
            )
        except RetrievalPathUnavailable as exc:
            del exc
            return _LaneOutcome(
                path=provider.path,
                status=RetrievalLaneStatus.UNAVAILABLE,
                candidates=[],
                latency_ms=(perf_counter() - started) * 1000,
                error=f"{provider.path.value} retrieval provider unavailable",
            )
        except TimeoutError:
            return _LaneOutcome(
                path=provider.path,
                status=RetrievalLaneStatus.TIMED_OUT,
                candidates=[],
                latency_ms=(perf_counter() - started) * 1000,
                error=f"{provider.path.value} retrieval timed out",
            )
        except Exception as exc:
            return _LaneOutcome(
                path=provider.path,
                status=RetrievalLaneStatus.FAILED,
                candidates=[],
                latency_ms=(perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: retrieval lane failed",
            )

    @staticmethod
    def _mode(outcomes: list[_LaneOutcome]) -> str:
        successful = {
            outcome.path
            for outcome in outcomes
            if outcome.status == RetrievalLaneStatus.SUCCESS
        }
        if successful == {RetrievalPath.VECTOR, RetrievalPath.GRAPH}:
            return "dual"
        if RetrievalPath.VECTOR in successful:
            return "vector_only"
        if RetrievalPath.GRAPH in successful:
            return "graph_only"
        return "unavailable"

    def _fuse(
        self,
        outcomes: list[_LaneOutcome],
        request: DualRetrievalRequest,
    ) -> tuple[list[FusedRetrievalEvidence], int, int, bool]:
        groups: dict[str, dict] = {}
        candidate_count = 0
        contributed_paths: set[tuple[RetrievalPath, str]] = set()

        for outcome in outcomes:
            if outcome.status != RetrievalLaneStatus.SUCCESS:
                continue
            for rank, candidate in enumerate(outcome.candidates, start=1):
                if (
                    request.allowed_memory_types
                    and candidate.evidence_type
                    not in request.allowed_memory_types
                ):
                    continue
                content = str(candidate.content or "").strip()
                if not content:
                    continue
                candidate_count += 1
                fingerprint = self._fingerprint(content)
                group = groups.setdefault(
                    fingerprint,
                    {
                        "content": content,
                        "evidence_type": candidate.evidence_type,
                        "fusion_score": 0.0,
                        "best_score": float(candidate.score),
                        "sources": [],
                    },
                )
                contribution_key = (candidate.path, fingerprint)
                if contribution_key not in contributed_paths:
                    group["fusion_score"] += 1.0 / (self.RRF_K + rank)
                    contributed_paths.add(contribution_key)
                group["best_score"] = max(
                    group["best_score"],
                    float(candidate.score),
                )
                group["sources"].append(
                    RetrievalSourceReference(
                        path=candidate.path,
                        source_id=candidate.source_id,
                        rank=rank,
                        score=float(candidate.score),
                        metadata=dict(candidate.metadata),
                    )
                )

        ordered = sorted(
            groups.items(),
            key=lambda item: (
                -float(item[1]["fusion_score"]),
                -float(item[1]["best_score"]),
                item[0],
            ),
        )

        evidence: list[FusedRetrievalEvidence] = []
        chars_used = 0
        truncated = False
        for fingerprint, group in ordered:
            if len(evidence) >= request.top_k:
                truncated = True
                break
            remaining = request.char_budget - chars_used
            if remaining <= 0:
                truncated = True
                break
            content = group["content"]
            item_truncated = len(content) > remaining
            if item_truncated:
                content = content[:remaining]
                truncated = True
            sources = sorted(
                group["sources"],
                key=lambda source: (
                    0 if source.path == RetrievalPath.VECTOR else 1,
                    source.rank,
                    source.source_id,
                ),
            )
            source_paths = list(
                dict.fromkeys(source.path for source in sources)
            )
            evidence.append(
                FusedRetrievalEvidence(
                    evidence_id=f"FUSED:{fingerprint[:24]}",
                    content=content,
                    evidence_type=str(group["evidence_type"] or "other"),
                    source_paths=source_paths,
                    sources=sources,
                    fusion_score=float(group["fusion_score"]),
                    truncated=item_truncated,
                )
            )
            chars_used += len(content)
            if item_truncated:
                break

        return (
            evidence,
            chars_used,
            max(candidate_count - len(groups), 0),
            truncated,
        )

    async def retrieve(
        self,
        request: DualRetrievalRequest,
    ) -> DualRetrievalResult:
        candidate_k = min(max(request.top_k * 3, 12), 60)
        outcomes = await asyncio.gather(
            self._run_lane(self.vector_provider, request, candidate_k),
            self._run_lane(self.graph_provider, request, candidate_k),
        )
        evidence, chars_used, deduplicated_count, truncated = self._fuse(
            list(outcomes),
            request,
        )
        mode = self._mode(list(outcomes))
        return DualRetrievalResult(
            mode=mode,
            degraded=(mode != "dual"),
            evidence=evidence,
            lanes=[
                RetrievalLaneDiagnostic(
                    path=outcome.path,
                    status=outcome.status,
                    latency_ms=outcome.latency_ms,
                    candidate_count=len(outcome.candidates),
                    error=outcome.error,
                )
                for outcome in outcomes
            ],
            char_budget=request.char_budget,
            chars_used=chars_used,
            truncated=truncated,
            deduplicated_count=deduplicated_count,
        )


dual_path_retriever = DualPathRetriever()
