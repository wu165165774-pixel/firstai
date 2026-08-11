from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.rag.memory_indexer import memory_indexer
from app.rag.faiss_store import faiss_store

@dataclass(
    frozen=True,
    slots=True,
)
class MemoryIndexConsistencyResult:

    sqlite_count: int

    faiss_count_before: int

    faiss_count_after: int

    missing_in_faiss: int

    orphaned_in_faiss: int

    rebuilt: bool

    consistent: bool

    error: str | None = None


class MemoryIndexConsistencyService:
    """
    检查 SQLite 长期记忆与 FAISS 向量索引是否一致。

    SQLite 是主存储。
    FAISS 出现缺失、孤立或数量不一致时，从 SQLite 全量重建。
    """

    def __init__(
        self,
        db_path: str | None = None,
        retry_count: int = 5,
        retry_delay_seconds: float = 3.0,
    ) -> None:

        self.db_path = (
            db_path
            or os.getenv(
                "MEMORY_DB_PATH",
                "/app/data/memory.db",
            )
        )

        self.retry_count = max(
            int(retry_count),
            1,
        )

        self.retry_delay_seconds = max(
            float(retry_delay_seconds),
            0.0,
        )

        self._lock = asyncio.Lock()

    def _load_sqlite_memories(
        self,
    ) -> list[tuple[str, str]]:

        with sqlite3.connect(
            self.db_path
        ) as conn:

            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(memories)"
                ).fetchall()
            }

            tier_filter = ""
            if "memory_tier" in columns:
                tier_filter = (
                    " AND memory_tier IN "
                    "('working', 'long_term')"
                )

            rows = conn.execute(
                f"""
                SELECT
                    id,
                    content
                FROM memories
                WHERE id IS NOT NULL
                  AND id != ''
                  AND content IS NOT NULL
                  AND content != ''
                  {tier_filter}
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [
            (
                str(memory_id),
                str(content),
            )
            for memory_id, content
            in rows
        ]

    async def _rebuild_with_retry(
        self,
        memories: list[tuple[str, str]],
    ) -> int:

        last_error: Exception | None = None

        for attempt in range(
            1,
            self.retry_count + 1,
        ):

            try:

                return await memory_indexer.rebuild(
                    memories
                )

            except Exception as exc:

                last_error = exc

                logger.warning(
                    "Memory FAISS rebuild attempt failed: "
                    f"attempt={attempt}/{self.retry_count}, "
                    f"error={exc}"
                )

                if attempt < self.retry_count:

                    await asyncio.sleep(
                        self.retry_delay_seconds
                    )

        assert last_error is not None

        raise last_error

    async def check_and_repair(
        self,
    ) -> MemoryIndexConsistencyResult:

        async with self._lock:

            memories = await asyncio.to_thread(
                self._load_sqlite_memories
            )

            sqlite_ids = {
                memory_id
                for memory_id, _
                in memories
            }

            faiss_ids_before = set(
                faiss_store.list_memory_ids()
            )

            missing_ids = (
                sqlite_ids
                - faiss_ids_before
            )

            orphaned_ids = (
                faiss_ids_before
                - sqlite_ids
            )

            consistent_before = (
                not missing_ids
                and not orphaned_ids
                and len(sqlite_ids)
                == len(faiss_ids_before)
            )

            if consistent_before:

                logger.info(
                    "Memory index consistency check passed: "
                    f"sqlite_count={len(sqlite_ids)}, "
                    f"faiss_count={len(faiss_ids_before)}"
                )

                return MemoryIndexConsistencyResult(
                    sqlite_count=len(
                        sqlite_ids
                    ),
                    faiss_count_before=len(
                        faiss_ids_before
                    ),
                    faiss_count_after=len(
                        faiss_ids_before
                    ),
                    missing_in_faiss=0,
                    orphaned_in_faiss=0,
                    rebuilt=False,
                    consistent=True,
                )

            logger.warning(
                "Memory index inconsistency detected: "
                f"sqlite_count={len(sqlite_ids)}, "
                f"faiss_count={len(faiss_ids_before)}, "
                f"missing_in_faiss={len(missing_ids)}, "
                f"orphaned_in_faiss={len(orphaned_ids)}"
            )

            try:

                rebuilt_count = (
                    await self._rebuild_with_retry(
                        memories
                    )
                )

            except Exception as exc:

                logger.exception(
                    "Memory index automatic rebuild failed"
                )

                return MemoryIndexConsistencyResult(
                    sqlite_count=len(
                        sqlite_ids
                    ),
                    faiss_count_before=len(
                        faiss_ids_before
                    ),
                    faiss_count_after=int(
                        memory_indexer.stats().get(
                            "count",
                            0,
                        )
                    ),
                    missing_in_faiss=len(
                        missing_ids
                    ),
                    orphaned_in_faiss=len(
                        orphaned_ids
                    ),
                    rebuilt=False,
                    consistent=False,
                    error=str(exc),
                )

            faiss_ids_after = set(
                faiss_store.list_memory_ids()
            )

            consistent_after = (
                sqlite_ids
                == faiss_ids_after
                and rebuilt_count
                == len(sqlite_ids)
            )

            if consistent_after:

                logger.info(
                    "Memory index automatic rebuild complete: "
                    f"count={rebuilt_count}"
                )

            else:

                logger.error(
                    "Memory index is still inconsistent "
                    "after rebuild: "
                    f"sqlite_count={len(sqlite_ids)}, "
                    f"faiss_count={len(faiss_ids_after)}"
                )

            return MemoryIndexConsistencyResult(
                sqlite_count=len(
                    sqlite_ids
                ),
                faiss_count_before=len(
                    faiss_ids_before
                ),
                faiss_count_after=len(
                    faiss_ids_after
                ),
                missing_in_faiss=len(
                    missing_ids
                ),
                orphaned_in_faiss=len(
                    orphaned_ids
                ),
                rebuilt=True,
                consistent=consistent_after,
            )

    async def status(
        self,
    ) -> dict[str, Any]:

        result = await self.check_and_repair()

        return {
            "sqlite_count": result.sqlite_count,
            "faiss_count_before": (
                result.faiss_count_before
            ),
            "faiss_count_after": (
                result.faiss_count_after
            ),
            "missing_in_faiss": (
                result.missing_in_faiss
            ),
            "orphaned_in_faiss": (
                result.orphaned_in_faiss
            ),
            "rebuilt": result.rebuilt,
            "consistent": result.consistent,
            "error": result.error,
        }


memory_index_consistency_service = (
    MemoryIndexConsistencyService()
)
