from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.memory.storage.sqlite import (
    SQLiteMemoryStorage,
)
from app.retrieval.schemas import DualRetrievalRequest
from app.retrieval.service import dual_path_retriever


@dataclass(frozen=True)
class GroundingMemory:

    id: str
    memory_type: str
    content: str
    memory_tier: str = "long_term"
    similarity: float | None = None
    hybrid_score: float | None = None
    source_paths: tuple[str, ...] = ("vector",)
    fusion_score: float | None = None


@dataclass(frozen=True)
class GroundingRetrieval:
    memories: list[GroundingMemory]
    mode: str
    degraded: bool
    lanes: list[dict[str, Any]]


class AgentGroundingService:

    def __init__(
        self,
        storage: SQLiteMemoryStorage | None = None,
    ) -> None:

        self._storage = (
            storage
            or SQLiteMemoryStorage()
        )

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_memory_type(
        value: Any,
    ) -> str:

        if hasattr(value, "value"):
            value = value.value

        return str(
            value or ""
        ).strip().lower()

    @staticmethod
    def _extract_memory_id(
        memory: Any,
    ) -> str:

        value = getattr(
            memory,
            "memory_id",
            None,
        )

        if not value:
            value = getattr(
                memory,
                "id",
                "",
            )

        return str(
            value or ""
        ).strip()

    def _convert_memory(
        self,
        memory: Any,
    ) -> GroundingMemory | None:

        content = str(
            getattr(
                memory,
                "content",
                "",
            )
            or ""
        ).strip()

        if not content:
            return None

        return GroundingMemory(
            id=self._extract_memory_id(
                memory
            ),
            memory_type=(
                self._normalize_memory_type(
                    getattr(
                        memory,
                        "memory_type",
                        "",
                    )
                )
            ),
            content=content,
            memory_tier=(
                self._normalize_memory_type(
                    getattr(
                        memory,
                        "memory_tier",
                        "long_term",
                    )
                )
            ),
            similarity=(
                self._optional_float(
                    getattr(
                        memory,
                        "similarity",
                        None,
                    )
                )
            ),
            hybrid_score=(
                self._optional_float(
                    getattr(
                        memory,
                        "hybrid_score",
                        None,
                    )
                )
            ),
            source_paths=tuple(
                str(
                    path.value
                    if hasattr(path, "value")
                    else path
                )
                for path in getattr(
                    memory,
                    "source_paths",
                    ("vector",),
                )
            ),
            fusion_score=(
                self._optional_float(
                    getattr(memory, "fusion_score", None)
                )
            ),
        )

    @staticmethod
    def _normalize_allowed_types(
        allowed_memory_types: (
            set[str]
            | frozenset[str]
            | None
        ),
    ) -> set[str] | None:

        if not allowed_memory_types:
            return None

        result = {
            str(memory_type).strip().lower()
            for memory_type
            in allowed_memory_types
            if str(memory_type).strip()
        }

        return result or None

    async def retrieve(
        self,
        user_id: str,
        novel_id: str,
        query: str,
        allowed_memory_types: (
            set[str]
            | frozenset[str]
            | None
        ) = None,
        top_k: int = 6,
        min_similarity: float = 0.35,
        active_entity_ids: list[str] | None = None,
        as_of_chapter: int | None = None,
    ) -> list[GroundingMemory]:

        result = await self.retrieve_with_diagnostics(
            user_id=user_id,
            novel_id=novel_id,
            query=query,
            allowed_memory_types=allowed_memory_types,
            top_k=top_k,
            min_similarity=min_similarity,
            active_entity_ids=active_entity_ids,
            as_of_chapter=as_of_chapter,
        )
        return result.memories

    async def retrieve_with_diagnostics(
        self,
        user_id: str,
        novel_id: str,
        query: str,
        allowed_memory_types: (
            set[str]
            | frozenset[str]
            | None
        ) = None,
        top_k: int = 6,
        min_similarity: float = 0.35,
        active_entity_ids: list[str] | None = None,
        as_of_chapter: int | None = None,
    ) -> GroundingRetrieval:

        user_id = str(
            user_id or ""
        ).strip()

        novel_id = str(
            novel_id or ""
        ).strip()

        query = str(
            query or ""
        ).strip()

        if not user_id or not novel_id or not query:
            return GroundingRetrieval(
                memories=[],
                mode="unavailable",
                degraded=True,
                lanes=[],
            )

        allowed_types = (
            self._normalize_allowed_types(
                allowed_memory_types
            )
        )

        requested_top_k = min(
            max(int(top_k), 1),
            20,
        )

        retrieval = await dual_path_retriever.retrieve(
            DualRetrievalRequest(
                user_id=user_id,
                novel_id=novel_id,
                query=query,
                top_k=min(
                    requested_top_k * 3,
                    20,
                ),
                min_vector_similarity=min_similarity,
                allowed_memory_types=sorted(allowed_types or set()),
                active_entity_ids=list(active_entity_ids or []),
                as_of=(
                    f"chapter:{as_of_chapter}"
                    if as_of_chapter is not None
                    else None
                ),
            )
        )

        results: list[GroundingMemory] = []
        seen: set[tuple[str, str]] = set()

        for candidate in retrieval.evidence:

            vector_source_id = next(
                (
                    source.source_id
                    for source in candidate.sources
                    if source.path.value == "vector"
                ),
                None,
            )
            memory = GroundingMemory(
                id=vector_source_id or candidate.evidence_id,
                memory_type=candidate.evidence_type,
                content=candidate.content,
                memory_tier=str(
                    next(
                        (
                            source.metadata.get("memory_tier")
                            for source in candidate.sources
                            if source.path.value == "vector"
                            and source.metadata.get("memory_tier")
                        ),
                        "graph",
                    )
                ),
                similarity=self._optional_float(
                    next(
                        (
                            source.metadata.get("similarity")
                            for source in candidate.sources
                            if source.path.value == "vector"
                        ),
                        None,
                    )
                ),
                hybrid_score=self._optional_float(
                    max(
                        (source.score for source in candidate.sources),
                        default=0.0,
                    )
                ),
                source_paths=tuple(
                    path.value for path in candidate.source_paths
                ),
                fusion_score=candidate.fusion_score,
            )

            if (
                allowed_types is not None
                and memory.memory_type
                not in allowed_types
            ):
                continue

            key = (
                memory.memory_type,
                memory.content,
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(memory)

            if len(results) >= requested_top_k:
                break

        return GroundingRetrieval(
            memories=results,
            mode=retrieval.mode,
            degraded=retrieval.degraded,
            lanes=[
                lane.model_dump(mode="json")
                for lane in retrieval.lanes
            ],
        )

    async def list_by_types(
        self,
        user_id: str,
        novel_id: str,
        allowed_memory_types: (
            set[str]
            | frozenset[str]
        ),
        top_k: int = 50,
    ) -> list[GroundingMemory]:

        user_id = str(
            user_id or ""
        ).strip()

        novel_id = str(
            novel_id or ""
        ).strip()

        allowed_types = (
            self._normalize_allowed_types(
                allowed_memory_types
            )
        )

        if (
            not user_id
            or not novel_id
            or not allowed_types
        ):
            return []

        limit = min(
            max(int(top_k), 1),
            100,
        )

        results: list[GroundingMemory] = []
        seen: set[tuple[str, str]] = set()

        for memory_type in sorted(
            allowed_types
        ):

            rows = await self._storage.query(
                user_id=user_id,
                novel_id=novel_id,
                memory_type=memory_type,
            )

            for row in rows:

                memory = self._convert_memory(
                    row
                )

                if memory is None:
                    continue

                key = (
                    memory.memory_type,
                    memory.content,
                )

                if key in seen:
                    continue

                seen.add(key)
                results.append(memory)

                if len(results) >= limit:
                    return results

        return results


agent_grounding_service = AgentGroundingService()
