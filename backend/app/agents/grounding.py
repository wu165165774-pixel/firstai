from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.memory.hybrid_retriever import (
    hybrid_memory_retriever,
)
from app.memory.storage.sqlite import (
    SQLiteMemoryStorage,
)


@dataclass(frozen=True)
class GroundingMemory:

    id: str
    memory_type: str
    content: str
    similarity: float | None = None
    hybrid_score: float | None = None


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
    ) -> list[GroundingMemory]:

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
            return []

        allowed_types = (
            self._normalize_allowed_types(
                allowed_memory_types
            )
        )

        requested_top_k = min(
            max(int(top_k), 1),
            20,
        )

        candidates = (
            await hybrid_memory_retriever.retrieve(
                user_id=user_id,
                novel_id=novel_id,
                query=query,
                top_k=min(
                    requested_top_k * 3,
                    30,
                ),
                min_similarity=min_similarity,
            )
        )

        results: list[GroundingMemory] = []
        seen: set[tuple[str, str]] = set()

        for candidate in candidates:

            memory = self._convert_memory(
                candidate
            )

            if memory is None:
                continue

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

        return results

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
