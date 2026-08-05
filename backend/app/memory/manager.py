from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from app.memory.retriever import MemoryRetriever
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.rag.memory_indexer import memory_indexer


class MemoryManager:

    def __init__(self) -> None:

        sqlite_storage = SQLiteMemoryStorage()

        self.storage = {
            "sqlite": sqlite_storage,
        }

        self.retriever = MemoryRetriever(
            sqlite_storage
        )

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
    ):

        return await self.storage["sqlite"].query(
            user_id,
            novel_id,
            memory_type,
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

        duplicate = await self.storage[
            "sqlite"
        ].find_duplicate(
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

            saved = await self.storage[
                "sqlite"
            ].update(
                duplicate
            )

        else:

            saved = await self.storage[
                "sqlite"
            ].save(
                memory
            )

        await self._sync_memory_to_faiss(
            saved
        )

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

        await self._sync_memory_to_faiss(
            saved
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
    ):
        """
        保留原有 Retriever 接口。

        注意：正式聊天上下文目前使用的是
        HybridMemoryRetriever。
        """

        return await self.retriever.retrieve(
            user_id,
            novel_id,
            query,
            top_k,
        )


memory_manager = MemoryManager()