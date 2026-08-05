from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.memory import hybrid_retriever as hybrid_module
from app.memory import manager as manager_module
from app.memory.hybrid_retriever import HybridMemoryRetriever
from app.memory.manager import MemoryManager
from app.rag import consistency as consistency_module
from app.rag.consistency import MemoryIndexConsistencyService


def create_memory_database(
    db_path: str,
    rows: list[tuple],
) -> None:
    """
    创建隔离的测试数据库。

    不使用真实 /app/data/memory.db，
    避免自动化测试污染开发数据。
    """

    with sqlite3.connect(db_path) as conn:

        conn.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                novel_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                hit_count INTEGER NOT NULL DEFAULT 1,
                score REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                last_accessed_at TEXT,
                metadata TEXT
            )
            """
        )

        conn.executemany(
            """
            INSERT INTO memories (
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
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

        conn.commit()


def memory_row(
    memory_id: str,
    user_id: str,
    novel_id: str,
    memory_type: str,
    content: str,
    importance: float = 0.5,
    hit_count: int = 1,
    score: float = 0.5,
) -> tuple:

    created_at = "2026-08-05T00:00:00"

    return (
        memory_id,
        user_id,
        novel_id,
        memory_type,
        content,
        importance,
        hit_count,
        score,
        created_at,
        created_at,
        created_at,
        "{}",
    )


class HybridMemoryRetrieverTests(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(self) -> None:

        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = str(
            Path(self.temp_directory.name)
            / "memory.db"
        )

        create_memory_database(
            self.db_path,
            [
                memory_row(
                    memory_id="m1",
                    user_id="user001",
                    novel_id="novel001",
                    memory_type="character",
                    content="林凡性格谨慎。",
                    importance=0.8,
                    hit_count=2,
                    score=1.0,
                ),
                memory_row(
                    memory_id="m2",
                    user_id="user001",
                    novel_id="novel001",
                    memory_type="character",
                    content="林凡来自青州。",
                    importance=0.9,
                    hit_count=3,
                    score=1.2,
                ),
                memory_row(
                    memory_id="m3",
                    user_id="another_user",
                    novel_id="another_novel",
                    memory_type="character",
                    content="敌人的性格十分谨慎。",
                    importance=1.0,
                    hit_count=10,
                    score=1.5,
                ),
            ],
        )

    def tearDown(self) -> None:

        self.temp_directory.cleanup()

    async def test_semantic_results_are_filtered_and_ranked(
        self,
    ) -> None:

        retriever = HybridMemoryRetriever(
            db_path=self.db_path
        )

        semantic_hits = [
            SimpleNamespace(
                memory_id="m3",
                similarity=0.95,
            ),
            SimpleNamespace(
                memory_id="m1",
                similarity=0.80,
            ),
            SimpleNamespace(
                memory_id="m2",
                similarity=0.35,
            ),
        ]

        mocked_search = AsyncMock(
            return_value=semantic_hits
        )

        with (
            patch.object(
                hybrid_module.memory_indexer,
                "stats",
                return_value={
                    "count": 3,
                    "dimension": 1024,
                },
            ),
            patch.object(
                hybrid_module.memory_indexer,
                "search",
                new=mocked_search,
            ),
        ):

            results = await retriever.retrieve(
                user_id="user001",
                novel_id="novel001",
                query="谁做事很小心？",
                top_k=5,
                min_similarity=0.0,
            )

        result_ids = [
            item.memory_id
            for item in results
        ]

        # m3 相似度最高，但属于另一个用户和小说，
        # 必须被数据隔离规则过滤。
        self.assertNotIn(
            "m3",
            result_ids,
        )

        self.assertEqual(
            result_ids,
            [
                "m1",
                "m2",
            ],
        )

        self.assertEqual(
            results[0].content,
            "林凡性格谨慎。",
        )

        self.assertGreater(
            results[0].hybrid_score,
            results[1].hybrid_score,
        )

        mocked_search.assert_awaited_once()

    async def test_nonexistent_novel_returns_no_results(
        self,
    ) -> None:

        retriever = HybridMemoryRetriever(
            db_path=self.db_path
        )

        mocked_search = AsyncMock(
            return_value=[
                SimpleNamespace(
                    memory_id="m1",
                    similarity=0.90,
                )
            ]
        )

        with (
            patch.object(
                hybrid_module.memory_indexer,
                "stats",
                return_value={
                    "count": 1,
                },
            ),
            patch.object(
                hybrid_module.memory_indexer,
                "search",
                new=mocked_search,
            ),
        ):

            results = await retriever.retrieve(
                user_id="user001",
                novel_id="novel_not_exist",
                query="林凡是什么性格？",
                top_k=5,
                min_similarity=0.0,
            )

        self.assertEqual(
            results,
            [],
        )


class MemoryManagerSyncTests(
    unittest.IsolatedAsyncioTestCase
):

    @staticmethod
    def create_manager(
        storage,
    ) -> MemoryManager:
        """
        绕过 MemoryManager.__init__，
        避免测试过程中初始化真实 SQLite 数据库。
        """

        manager = MemoryManager.__new__(
            MemoryManager
        )

        manager.storage = {
            "sqlite": storage,
        }

        manager.retriever = None

        return manager

    async def test_add_memory_upserts_faiss(
        self,
    ) -> None:

        memory = SimpleNamespace(
            id="memory-add-001",
            user_id="user001",
            novel_id="novel001",
            memory_type="character",
            content="林凡性格谨慎。",
            importance=0.8,
            hit_count=1,
        )

        storage = SimpleNamespace(
            find_duplicate=AsyncMock(
                return_value=None
            ),
            save=AsyncMock(
                return_value=memory
            ),
            update=AsyncMock(),
            delete=AsyncMock(),
            query=AsyncMock(),
        )

        manager = self.create_manager(
            storage
        )

        mocked_upsert = AsyncMock(
            return_value=True
        )

        with patch.object(
            manager_module.memory_indexer,
            "upsert_memory",
            new=mocked_upsert,
        ):

            result = await manager.add_memory(
                memory
            )

        self.assertIs(
            result,
            memory,
        )

        storage.save.assert_awaited_once_with(
            memory
        )

        mocked_upsert.assert_awaited_once_with(
            memory
        )

    async def test_delete_memory_removes_sqlite_and_faiss(
        self,
    ) -> None:

        memory_id = "memory-delete-001"

        storage = SimpleNamespace(
            delete=AsyncMock(
                return_value={
                    "id": memory_id,
                }
            ),
            find_duplicate=AsyncMock(),
            save=AsyncMock(),
            update=AsyncMock(),
            query=AsyncMock(),
        )

        manager = self.create_manager(
            storage
        )

        mocked_remove = AsyncMock(
            return_value=True
        )

        with patch.object(
            manager_module.memory_indexer,
            "remove",
            new=mocked_remove,
        ):

            result = await manager.delete_memory(
                memory_id
            )

        self.assertEqual(
            result,
            {
                "id": memory_id,
                "sqlite_deleted": True,
                "faiss_deleted": True,
            },
        )

        storage.delete.assert_awaited_once_with(
            memory_id
        )

        mocked_remove.assert_awaited_once_with(
            memory_id
        )

    async def test_missing_memory_returns_none(
        self,
    ) -> None:

        memory_id = "memory-not-exist"

        storage = SimpleNamespace(
            delete=AsyncMock(
                return_value=None
            ),
            find_duplicate=AsyncMock(),
            save=AsyncMock(),
            update=AsyncMock(),
            query=AsyncMock(),
        )

        manager = self.create_manager(
            storage
        )

        mocked_remove = AsyncMock(
            return_value=False
        )

        with patch.object(
            manager_module.memory_indexer,
            "remove",
            new=mocked_remove,
        ):

            result = await manager.delete_memory(
                memory_id
            )

        self.assertIsNone(
            result
        )
        
class MemoryManagerRetrieveTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_retrieve_memory_uses_hybrid_retriever(
        self,
    ) -> None:

        storage = SimpleNamespace(
            delete=AsyncMock(),
            find_duplicate=AsyncMock(),
            save=AsyncMock(),
            update=AsyncMock(),
            query=AsyncMock(),
        )

        manager = MemoryManager.__new__(
            MemoryManager
        )

        manager.storage = {
            "sqlite": storage,
        }

        hybrid_result = SimpleNamespace(
            memory_id="m1",
            user_id="user001",
            novel_id="novel001",
            memory_type="character",
            content="林凡性格谨慎。",
            importance=0.8,
            hit_count=2,
            base_score=1.0,
            similarity=0.82,
            hybrid_score=0.79,
        )

        mocked_retrieve = AsyncMock(
            return_value=[
                hybrid_result
            ]
        )

        with patch.object(
            manager_module.hybrid_memory_retriever,
            "retrieve",
            new=mocked_retrieve,
        ):

            results = await manager.retrieve_memory(
                user_id="user001",
                novel_id="novel001",
                query="谁做事很谨慎？",
                top_k=5,
            )

        mocked_retrieve.assert_awaited_once_with(
            user_id="user001",
            novel_id="novel001",
            query="谁做事很谨慎？",
            top_k=5,
            min_similarity=0.35,
        )

        self.assertEqual(
            len(results),
            1,
        )

        self.assertEqual(
            results[0]["id"],
            "m1",
        )

        self.assertEqual(
            results[0]["content"],
            "林凡性格谨慎。",
        )

        self.assertEqual(
            results[0]["similarity"],
            0.82,
        )

        self.assertEqual(
            results[0]["hybrid_score"],
            0.79,
        )

class MemoryIndexConsistencyTests(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(self) -> None:

        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = str(
            Path(self.temp_directory.name)
            / "memory.db"
        )

        self.rows = [
            memory_row(
                memory_id="m1",
                user_id="user001",
                novel_id="novel001",
                memory_type="character",
                content="林凡性格谨慎。",
            ),
            memory_row(
                memory_id="m2",
                user_id="user001",
                novel_id="novel001",
                memory_type="world",
                content="青云宗位于东荒大陆。",
            ),
        ]

        create_memory_database(
            self.db_path,
            self.rows,
        )

    def tearDown(self) -> None:

        self.temp_directory.cleanup()

    async def test_consistent_index_does_not_rebuild(
        self,
    ) -> None:

        service = MemoryIndexConsistencyService(
            db_path=self.db_path,
            retry_count=1,
            retry_delay_seconds=0,
        )

        mocked_rebuild = AsyncMock()

        with (
            patch.object(
                consistency_module.faiss_store,
                "list_memory_ids",
                return_value=[
                    "m1",
                    "m2",
                ],
            ),
            patch.object(
                consistency_module.memory_indexer,
                "rebuild",
                new=mocked_rebuild,
            ),
        ):

            result = await service.check_and_repair()

        self.assertTrue(
            result.consistent
        )

        self.assertFalse(
            result.rebuilt
        )

        self.assertEqual(
            result.sqlite_count,
            2,
        )

        self.assertEqual(
            result.faiss_count_before,
            2,
        )

        mocked_rebuild.assert_not_awaited()

    async def test_missing_vectors_trigger_rebuild(
        self,
    ) -> None:

        service = MemoryIndexConsistencyService(
            db_path=self.db_path,
            retry_count=1,
            retry_delay_seconds=0,
        )

        mocked_rebuild = AsyncMock(
            return_value=2
        )

        # 第一次调用：重建之前为空。
        # 第二次调用：重建之后包含 SQLite 中全部 ID。
        mocked_list_ids = unittest.mock.Mock(
            side_effect=[
                [],
                [
                    "m1",
                    "m2",
                ],
            ]
        )

        with (
            patch.object(
                consistency_module.faiss_store,
                "list_memory_ids",
                new=mocked_list_ids,
            ),
            patch.object(
                consistency_module.memory_indexer,
                "rebuild",
                new=mocked_rebuild,
            ),
        ):

            result = await service.check_and_repair()

        self.assertTrue(
            result.consistent
        )

        self.assertTrue(
            result.rebuilt
        )

        self.assertEqual(
            result.sqlite_count,
            2,
        )

        self.assertEqual(
            result.faiss_count_before,
            0,
        )

        self.assertEqual(
            result.faiss_count_after,
            2,
        )

        self.assertEqual(
            result.missing_in_faiss,
            2,
        )

        mocked_rebuild.assert_awaited_once()

        rebuild_memories = (
            mocked_rebuild.await_args.args[0]
        )

        self.assertEqual(
            {
                memory_id
                for memory_id, _
                in rebuild_memories
            },
            {
                "m1",
                "m2",
            },
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )

    async def test_retrieve_memory_uses_hybrid_retriever(
        self,
    ) -> None:

        storage = SimpleNamespace(
            delete=AsyncMock(),
            find_duplicate=AsyncMock(),
            save=AsyncMock(),
            update=AsyncMock(),
            query=AsyncMock(),
        )

        manager = self.create_manager(
            storage
        )

        hybrid_result = SimpleNamespace(
            memory_id="m1",
            user_id="user001",
            novel_id="novel001",
            memory_type="character",
            content="林凡性格谨慎。",
            importance=0.8,
            hit_count=2,
            base_score=1.0,
            similarity=0.82,
            hybrid_score=0.79,
        )

        mocked_retrieve = AsyncMock(
            return_value=[
                hybrid_result
            ]
        )

        with patch.object(
            manager_module.hybrid_memory_retriever,
            "retrieve",
            new=mocked_retrieve,
        ):

            results = await manager.retrieve_memory(
                user_id="user001",
                novel_id="novel001",
                query="谁做事很谨慎？",
                top_k=5,
            )

        mocked_retrieve.assert_awaited_once_with(
            user_id="user001",
            novel_id="novel001",
            query="谁做事很谨慎？",
            top_k=5,
            min_similarity=0.35,
        )

        self.assertEqual(
            len(results),
            1,
        )

        self.assertEqual(
            results[0]["id"],
            "m1",
        )

        self.assertEqual(
            results[0]["content"],
            "林凡性格谨慎。",
        )

        self.assertEqual(
            results[0]["similarity"],
            0.82,
        )

        self.assertEqual(
            results[0]["hybrid_score"],
            0.79,
        )