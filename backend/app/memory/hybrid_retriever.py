from __future__ import annotations

import asyncio
import math
import os
import sqlite3

from dataclasses import dataclass

from loguru import logger

from app.rag.memory_indexer import memory_indexer


@dataclass(
    frozen=True,
    slots=True,
)
class HybridMemoryResult:
    """
    FAISS 语义检索与 SQLite 记忆评分融合后的结果。
    """

    memory_id: str

    user_id: str

    novel_id: str

    memory_type: str

    content: str

    importance: float

    hit_count: int

    base_score: float

    similarity: float

    hybrid_score: float


class HybridMemoryRetriever:
    """
    混合记忆检索器。

    检索流程：

    1. 使用 Embedding + FAISS 做语义召回；
    2. 使用 SQLite 获取完整记忆；
    3. 使用 user_id 和 novel_id 做数据隔离；
    4. 综合语义相似度、重要度、命中次数和基础分数排序。
    """

    def __init__(
        self,
        db_path: str | None = None,
        similarity_weight: float = 0.60,
        importance_weight: float = 0.20,
        base_score_weight: float = 0.15,
        hit_count_weight: float = 0.05,
        score_normalization_max: float = 1.5,
    ) -> None:

        self.db_path = (
            db_path
            or os.getenv(
                "MEMORY_DB_PATH",
                "/app/data/memory.db",
            )
        )

        self.similarity_weight = float(
            similarity_weight
        )

        self.importance_weight = float(
            importance_weight
        )

        self.base_score_weight = float(
            base_score_weight
        )

        self.hit_count_weight = float(
            hit_count_weight
        )

        self.score_normalization_max = float(
            score_normalization_max
        )

        if self.score_normalization_max <= 0:

            raise ValueError(
                "score_normalization_max "
                "must be greater than zero."
            )

        total_weight = (
            self.similarity_weight
            + self.importance_weight
            + self.base_score_weight
            + self.hit_count_weight
        )

        if total_weight <= 0:

            raise ValueError(
                "Hybrid retrieval weights "
                "must be greater than zero."
            )

        # 自动归一化权重，避免以后调整时总和不是 1。
        self.similarity_weight /= total_weight

        self.importance_weight /= total_weight

        self.base_score_weight /= total_weight

        self.hit_count_weight /= total_weight

    @staticmethod
    def _clamp(
        value: float,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:

        return max(
            minimum,
            min(
                float(value),
                maximum,
            ),
        )

    def _calculate_hybrid_score(
        self,
        similarity: float,
        importance: float,
        base_score: float,
        hit_count: int,
    ) -> float:
        """
        综合评分。

        similarity：
            FAISS 余弦相似度。

        importance：
            LLM 抽取时判断的重要程度。

        base_score：
            SQLite 中已有的动态 score。

        hit_count：
            同一条记忆重复出现或被命中的次数。
        """

        similarity_component = self._clamp(
            similarity
        )

        importance_component = self._clamp(
            importance
        )

        base_score_component = self._clamp(
            max(
                float(base_score),
                0.0,
            )
            / self.score_normalization_max
        )

        # 使用对数降低超高 hit_count 对排名的影响。
        hit_count_component = self._clamp(
            math.log1p(
                max(
                    int(hit_count),
                    0,
                )
            )
            / math.log1p(10)
        )

        hybrid_score = (
            similarity_component
            * self.similarity_weight

            + importance_component
            * self.importance_weight

            + base_score_component
            * self.base_score_weight

            + hit_count_component
            * self.hit_count_weight
        )

        return float(
            hybrid_score
        )

    def _load_memory_rows(
        self,
        memory_ids: list[str],
        user_id: str,
        novel_id: str,
    ) -> list[sqlite3.Row]:

        if not memory_ids:
            return []

        placeholders = ",".join(
            "?"
            for _ in memory_ids
        )

        sql = f"""
            SELECT
                id,
                user_id,
                novel_id,
                memory_type,
                content,
                importance,
                hit_count,
                score,
                created_at,
                updated_at,
                last_accessed_at,
                metadata
            FROM memories
            WHERE user_id = ?
              AND novel_id = ?
              AND id IN ({placeholders})
              AND content IS NOT NULL
              AND content != ''
        """

        params = [
            user_id,
            novel_id,
            *memory_ids,
        ]

        with sqlite3.connect(
            self.db_path
        ) as conn:

            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                sql,
                params,
            ).fetchall()

        return rows

    async def retrieve(
        self,
        user_id: str,
        novel_id: str,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.25,
    ) -> list[HybridMemoryResult]:

        user_id = str(
            user_id
        ).strip()

        novel_id = str(
            novel_id
        ).strip()

        query = str(
            query
            or ""
        ).strip()

        if not user_id:
            raise ValueError(
                "user_id must not be empty."
            )

        if not novel_id:
            raise ValueError(
                "novel_id must not be empty."
            )

        if not query or top_k <= 0:
            return []

        stats = memory_indexer.stats()

        index_count = int(
            stats.get(
                "count",
                0,
            )
        )

        if index_count <= 0:

            logger.info(
                "Hybrid retrieval skipped: "
                "FAISS index is empty"
            )

            return []

        # 当前 FAISS 是全局索引。
        #
        # 为确保按 user_id 和 novel_id 过滤后仍有足够候选，
        # 先多取一些语义候选。
        candidate_k = min(
            index_count,
            max(
                int(top_k) * 20,
                100,
            ),
            900,
        )

        semantic_hits = await memory_indexer.search(
            query=query,
            top_k=candidate_k,
            min_similarity=0.0,
        )

        if not semantic_hits:
            return []

        similarity_by_id = {
            hit.memory_id: float(
                hit.similarity
            )
            for hit in semantic_hits
        }

        memory_ids = list(
            similarity_by_id.keys()
        )

        rows = await asyncio.to_thread(
            self._load_memory_rows,
            memory_ids,
            user_id,
            novel_id,
        )

        results: list[
            HybridMemoryResult
        ] = []

        for row in rows:

            memory_id = str(
                row["id"]
            )

            similarity = float(
                similarity_by_id.get(
                    memory_id,
                    0.0,
                )
            )

            if similarity < min_similarity:
                continue

            importance = float(
                row["importance"]
                if row["importance"] is not None
                else 0.5
            )

            hit_count = int(
                row["hit_count"]
                if row["hit_count"] is not None
                else 0
            )

            base_score = float(
                row["score"]
                if row["score"] is not None
                else 0.0
            )

            hybrid_score = (
                self._calculate_hybrid_score(
                    similarity=similarity,
                    importance=importance,
                    base_score=base_score,
                    hit_count=hit_count,
                )
            )

            results.append(
                HybridMemoryResult(
                    memory_id=memory_id,
                    user_id=str(
                        row["user_id"]
                    ),
                    novel_id=str(
                        row["novel_id"]
                    ),
                    memory_type=str(
                        row["memory_type"]
                    ),
                    content=str(
                        row["content"]
                    ),
                    importance=importance,
                    hit_count=hit_count,
                    base_score=base_score,
                    similarity=similarity,
                    hybrid_score=hybrid_score,
                )
            )

        results.sort(
            key=lambda item: (
                item.hybrid_score,
                item.similarity,
                item.importance,
                item.hit_count,
            ),
            reverse=True,
        )

        selected = results[
            :int(top_k)
        ]

        logger.info(
            "Hybrid memory retrieval complete: "
            f"user_id={user_id}, "
            f"novel_id={novel_id}, "
            f"query={query!r}, "
            f"semantic_candidates={len(semantic_hits)}, "
            f"filtered={len(results)}, "
            f"returned={len(selected)}"
        )

        for item in selected:

            logger.debug(
                "Hybrid memory hit: "
                f"id={item.memory_id}, "
                f"type={item.memory_type}, "
                f"similarity={item.similarity:.4f}, "
                f"hybrid_score={item.hybrid_score:.4f}, "
                f"content={item.content!r}"
            )

        return selected


hybrid_memory_retriever = HybridMemoryRetriever()