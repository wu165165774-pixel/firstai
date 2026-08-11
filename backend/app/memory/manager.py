from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.memory.schemas import (
    MemoryLifecycleSweepResult,
    MemoryPromotionRequest,
    MemoryPromotionResult,
    MemoryTier,
)
from app.rag.memory_indexer import memory_indexer
from app.memory.hybrid_retriever import (
    hybrid_memory_retriever,
)

class MemoryManager:

    def __init__(
        self,
        db_path: str | None = None,
    ) -> None:

        sqlite_storage = SQLiteMemoryStorage(
            db_path=db_path,
        )

        self.storage = {
            "sqlite": sqlite_storage,
        }

    @staticmethod
    def _is_indexed_memory(memory: Any) -> bool:

        tier = getattr(
            memory,
            "memory_tier",
            MemoryTier.LONG_TERM,
        )
        if hasattr(tier, "value"):
            tier = tier.value

        return str(tier) in {
            MemoryTier.WORKING.value,
            MemoryTier.LONG_TERM.value,
        }



    async def _sync_memory_to_faiss(
        self,
        memory: Any,
    ) -> bool:
        """
        将 SQLite 中已经保存成功的记忆同步至 FAISS。

        SQLite 是主存储。FAISS 同步失败时不回滚 SQLite，
        后续可通过全量 rebuild 恢复索引。
        """

        try:

            await memory_indexer.upsert_memory(
                memory
            )

            logger.info(
                "MemoryManager FAISS upsert complete: "
                f"memory_id={memory.id}"
            )

            return True

        except Exception:

            logger.exception(
                "MemoryManager FAISS upsert failed: "
                f"memory_id={getattr(memory, 'id', None)}"
            )

            return False

    async def get_memory(
        self,
        user_id: str,
        novel_id: str,
        memory_type=None,
        memory_tier=None,
        session_id: str | None = None,
        include_expired: bool = False,
    ):

        return await self.storage["sqlite"].query(
            user_id,
            novel_id,
            memory_type,
            memory_tier,
            session_id,
            include_expired,
        )

    async def delete_memory(
        self,
        memory_id: str,
    ):
        """
        删除 SQLite 记忆，并同步移除 FAISS 向量。

        即使 SQLite 中已经没有该记录，也会尝试清理可能残留的
        FAISS 向量。
        """

        memory_id = str(
            memory_id
        ).strip()

        if not memory_id:

            raise ValueError(
                "memory_id must not be empty."
            )

        sqlite_result = await self.storage[
            "sqlite"
        ].delete(
            memory_id
        )

        faiss_deleted = False

        try:

            faiss_deleted = await memory_indexer.remove(
                memory_id
            )

            logger.info(
                "MemoryManager FAISS delete complete: "
                f"memory_id={memory_id}, "
                f"removed={faiss_deleted}"
            )

        except Exception:

            logger.exception(
                "MemoryManager FAISS delete failed: "
                f"memory_id={memory_id}"
            )

        if (
            sqlite_result is None
            and not faiss_deleted
        ):

            return None

        return {
            "id": memory_id,
            "sqlite_deleted": (
                sqlite_result is not None
            ),
            "faiss_deleted": faiss_deleted,
        }

    async def add_memory(
        self,
        memory,
    ):
        """
        新增记忆。

        如果存在完全相同的记忆，则增加 hit_count 并更新原记录。
        无论新增还是去重更新，最后都同步 upsert FAISS。
        """

        storage = self.storage["sqlite"]

        if hasattr(storage, "find_duplicate_scoped"):
            duplicate = await storage.find_duplicate_scoped(
                memory.user_id,
                memory.novel_id,
                memory.memory_type,
                memory.content,
                getattr(
                    memory,
                    "memory_tier",
                    MemoryTier.LONG_TERM,
                ),
                getattr(memory, "session_id", None),
            )
        else:
            duplicate = await storage.find_duplicate(
                memory.user_id,
                memory.novel_id,
                memory.memory_type,
                memory.content,
            )

        if duplicate:

            logger.info(
                "Duplicate memory detected: "
                f"memory_id={duplicate.id}"
            )

            duplicate.hit_count += 1

            duplicate.importance = max(
                duplicate.importance,
                memory.importance,
            )

            now = datetime.utcnow()

            duplicate.updated_at = now
            duplicate.last_accessed_at = now

            saved = await storage.update(
                duplicate
            )

        else:

            saved = await storage.save(
                memory
            )

        if self._is_indexed_memory(saved):
            await self._sync_memory_to_faiss(saved)

        return saved

    async def update_memory(
        self,
        memory,
    ):
        """
        更新 SQLite 记忆，并同步刷新 FAISS 向量。
        """

        saved = await self.storage[
            "sqlite"
        ].update(
            memory
        )

        if self._is_indexed_memory(saved):
            await self._sync_memory_to_faiss(saved)
        else:
            try:
                await memory_indexer.remove(str(saved.id))
            except Exception:
                logger.exception(
                    "MemoryManager FAISS cleanup failed: "
                    f"memory_id={saved.id}"
                )

        return saved

    async def find_duplicate(
        self,
        user_id: str,
        novel_id: str,
        memory_type,
        content: str,
    ):

        return await self.storage[
            "sqlite"
        ].find_duplicate(
            user_id,
            novel_id,
            memory_type,
            content,
        )

    async def retrieve_memory(
        self,
        user_id: str,
        novel_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[dict]:
        """
        使用 FAISS 语义召回与 SQLite 记忆评分进行混合检索。

        返回普通字典，便于 FastAPI JSON 序列化。
        """

        results = (
            await hybrid_memory_retriever.retrieve(
                user_id=user_id,
                novel_id=novel_id,
                query=query,
                top_k=top_k,
                min_similarity=0.35,
            )
        )

        return [
            {
                "id": item.memory_id,
                "user_id": item.user_id,
                "novel_id": item.novel_id,
                "memory_type": item.memory_type,
                "memory_tier": getattr(
                    item,
                    "memory_tier",
                    MemoryTier.LONG_TERM.value,
                ),
                "session_id": getattr(
                    item,
                    "session_id",
                    None,
                ),
                "content": item.content,
                "importance": item.importance,
                "hit_count": item.hit_count,
                "base_score": item.base_score,
                "similarity": item.similarity,
                "hybrid_score": item.hybrid_score,
            }
            for item in results
        ]

    async def promote_memory(
        self,
        memory_id: str,
        payload: MemoryPromotionRequest,
    ) -> MemoryPromotionResult:

        memory, event = await self.storage["sqlite"].promote(
            memory_id,
            expected_revision=payload.expected_revision,
            target_tier=payload.target_tier,
            basis=payload.basis,
            reason=payload.reason,
        )

        if self._is_indexed_memory(memory):
            await self._sync_memory_to_faiss(memory)

        return MemoryPromotionResult(
            memory=memory,
            event=event,
        )

    async def list_lifecycle_events(
        self,
        memory_id: str,
    ):

        return await self.storage[
            "sqlite"
        ].list_lifecycle_events(memory_id)

    async def sweep_lifecycle(
        self,
        *,
        user_id: str,
        novel_id: str,
        session_id: str | None = None,
        now: datetime | None = None,
        dry_run: bool = False,
    ) -> MemoryLifecycleSweepResult:

        evicted = await self.storage["sqlite"].sweep_expired(
            user_id=user_id,
            novel_id=novel_id,
            session_id=session_id,
            now=now,
            dry_run=dry_run,
        )

        if not dry_run:
            for memory in evicted:
                try:
                    await memory_indexer.remove(str(memory.id))
                except Exception:
                    logger.exception(
                        "Memory lifecycle FAISS cleanup failed: "
                        f"memory_id={memory.id}"
                    )

        return MemoryLifecycleSweepResult(
            dry_run=dry_run,
            evicted_count=len(evicted),
            evicted_memory_ids=[
                str(memory.id)
                for memory in evicted
            ],
        )

    async def close_session(
        self,
        *,
        user_id: str,
        novel_id: str,
        session_id: str,
    ) -> MemoryLifecycleSweepResult:

        evicted = await self.storage["sqlite"].evict_session(
            user_id=user_id,
            novel_id=novel_id,
            session_id=session_id,
        )

        for memory in evicted:
            try:
                await memory_indexer.remove(str(memory.id))
            except Exception:
                logger.exception(
                    "Memory session FAISS cleanup failed: "
                    f"memory_id={memory.id}"
                )

        return MemoryLifecycleSweepResult(
            dry_run=False,
            evicted_count=len(evicted),
            evicted_memory_ids=[
                str(memory.id)
                for memory in evicted
            ],
        )



memory_manager = MemoryManager()
