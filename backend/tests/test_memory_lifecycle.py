from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import memory as memory_api_module
from app.main import app
from app.memory import context as context_module
from app.memory import extractor as extractor_module
from app.memory import manager as manager_module
from app.memory.context import MemoryContextBuilder
from app.memory.extractor import MemoryExtractor
from app.memory.manager import MemoryManager
from app.memory.schemas import (
    MemoryItem,
    MemoryLifecycleSweepRequest,
    MemoryPromotionRequest,
    MemoryTier,
    MemoryType,
)
from app.memory.storage.sqlite import (
    MemoryLifecycleConflictError,
    SQLiteMemoryStorage,
)
from app.rag.consistency import MemoryIndexConsistencyService


class MemoryLifecycleSchemaTests(unittest.TestCase):

    def test_content_type_and_lifecycle_tier_are_independent(self) -> None:

        memory = MemoryItem(
            user_id="user",
            novel_id="novel",
            memory_type=MemoryType.SHORT_TERM,
            memory_tier=MemoryTier.LONG_TERM,
            content="短句也可以成为跨会话证据。",
        )

        self.assertEqual(memory.memory_type, MemoryType.SHORT_TERM)
        self.assertEqual(memory.memory_tier, MemoryTier.LONG_TERM)

    def test_session_memory_requires_session_scope(self) -> None:

        with self.assertRaises(ValidationError):
            MemoryItem(
                user_id="user",
                novel_id="novel",
                memory_type=MemoryType.PLOT,
                memory_tier=MemoryTier.SESSION,
                content="当前正在讨论第一章。",
            )


class MemoryLifecycleMigrationTests(unittest.IsolatedAsyncioTestCase):

    async def test_legacy_rows_migrate_to_long_term(self) -> None:

        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "memory.db")
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
                        hit_count INTEGER DEFAULT 1,
                        score REAL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT,
                        last_accessed_at TEXT,
                        metadata TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO memories VALUES (
                        'legacy-1', 'user', 'novel', 'world',
                        '旧记忆仍可读取。', 0.8, 1, 0.9,
                        '2026-08-11T00:00:00',
                        '2026-08-11T00:00:00',
                        '2026-08-11T00:00:00', '{}'
                    )
                    """
                )
                conn.commit()

            storage = SQLiteMemoryStorage(db_path)
            memories = await storage.query("user", "novel")

            self.assertEqual(len(memories), 1)
            self.assertEqual(
                memories[0].memory_tier,
                MemoryTier.LONG_TERM,
            )
            self.assertEqual(memories[0].revision, 1)

            with sqlite3.connect(db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table'"
                    ).fetchall()
                }
            self.assertIn("memory_lifecycle_events", tables)


class MemoryLifecycleStorageTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:

        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp_directory.name) / "memory.db"
        )
        self.storage = SQLiteMemoryStorage(self.db_path)
        self.manager = MemoryManager(self.db_path)

    def tearDown(self) -> None:

        self.temp_directory.cleanup()

    @staticmethod
    def memory(
        *,
        tier: MemoryTier,
        content: str,
        session_id: str | None = None,
        importance: float = 0.8,
        expires_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> MemoryItem:

        return MemoryItem(
            user_id="user",
            novel_id="novel",
            memory_type=MemoryType.PLOT,
            memory_tier=tier,
            session_id=session_id,
            content=content,
            importance=importance,
            expires_at=expires_at,
            metadata=metadata or {},
        )

    async def test_session_duplicate_is_scoped_and_not_indexed(self) -> None:

        mocked_upsert = AsyncMock()
        with patch.object(
            manager_module.memory_indexer,
            "upsert_memory",
            new=mocked_upsert,
        ):
            first = await self.manager.add_memory(
                self.memory(
                    tier=MemoryTier.SESSION,
                    session_id="session-a",
                    content="当前正在处理潮钟线索。",
                )
            )
            reinforced = await self.manager.add_memory(
                self.memory(
                    tier=MemoryTier.SESSION,
                    session_id="session-a",
                    content="当前正在处理潮钟线索。",
                )
            )
            other_session = await self.manager.add_memory(
                self.memory(
                    tier=MemoryTier.SESSION,
                    session_id="session-b",
                    content="当前正在处理潮钟线索。",
                )
            )

        self.assertEqual(first.id, reinforced.id)
        self.assertEqual(reinforced.hit_count, 2)
        self.assertEqual(reinforced.revision, 2)
        self.assertNotEqual(first.id, other_session.id)
        mocked_upsert.assert_not_awaited()

    async def test_frequency_promotion_requires_reinforcement(self) -> None:

        memory = await self.manager.add_memory(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="潮钟坐标需要复核。",
                importance=0.2,
            )
        )

        with self.assertRaises(MemoryLifecycleConflictError):
            await self.manager.promote_memory(
                str(memory.id),
                MemoryPromotionRequest(
                    expected_revision=1,
                    target_tier="working",
                    basis="frequency",
                    reason="尚未重复。",
                ),
            )

        reinforced = await self.manager.add_memory(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="潮钟坐标需要复核。",
                importance=0.2,
            )
        )

        mocked_upsert = AsyncMock(return_value=1)
        with patch.object(
            manager_module.memory_indexer,
            "upsert_memory",
            new=mocked_upsert,
        ):
            result = await self.manager.promote_memory(
                str(memory.id),
                MemoryPromotionRequest(
                    expected_revision=reinforced.revision,
                    target_tier="working",
                    basis="frequency",
                    reason="当前任务中重复出现。",
                ),
            )

        self.assertEqual(result.memory.id, memory.id)
        self.assertEqual(result.memory.memory_tier, MemoryTier.WORKING)
        self.assertIsNone(result.memory.session_id)
        self.assertIsNotNone(result.memory.expires_at)
        self.assertEqual(result.memory.revision, 3)
        mocked_upsert.assert_awaited_once()

    async def test_promotion_is_adjacent_and_revision_guarded(self) -> None:

        memory = await self.storage.save(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="临时任务。",
            )
        )

        with self.assertRaises(MemoryLifecycleConflictError):
            await self.storage.promote(
                str(memory.id),
                expected_revision=1,
                target_tier="long_term",
                basis="user_confirmed",
                reason="不能跨层。",
            )

        with self.assertRaises(MemoryLifecycleConflictError):
            await self.storage.promote(
                str(memory.id),
                expected_revision=99,
                target_tier="working",
                basis="user_confirmed",
                reason="过期 revision。",
            )

    async def test_long_term_promotion_requires_authority(self) -> None:

        working = await self.storage.save(
            self.memory(
                tier=MemoryTier.WORKING,
                content="AMBER-17 是潮钟记录编号。",
                importance=0.9,
                metadata={
                    "source_reference": "manuscript:chapter-1:r1"
                },
            )
        )

        with self.assertRaises(MemoryLifecycleConflictError):
            await self.storage.promote(
                str(working.id),
                expected_revision=1,
                target_tier="long_term",
                basis="frequency",
                reason="重复本身不构成长期权威。",
            )

        promoted, event = await self.storage.promote(
            str(working.id),
            expected_revision=1,
            target_tier="long_term",
            basis="accepted_manuscript",
            reason="来源正文已接受。",
        )

        self.assertEqual(promoted.memory_tier, MemoryTier.LONG_TERM)
        self.assertIsNone(promoted.expires_at)
        self.assertEqual(event.payload["basis"], "accepted_manuscript")

    async def test_events_survive_storage_reopen(self) -> None:

        memory = await self.storage.save(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="待提升记录。",
            )
        )
        await self.storage.promote(
            str(memory.id),
            expected_revision=1,
            target_tier="working",
            basis="user_confirmed",
            reason="用户确认继续保留。",
        )

        reopened = SQLiteMemoryStorage(self.db_path)
        events = await reopened.list_lifecycle_events(str(memory.id))

        self.assertEqual(
            [event.event_type for event in events],
            ["memory_created", "memory_promoted"],
        )

    async def test_sweep_evicts_only_expired_ephemeral_tiers(self) -> None:

        now = datetime.utcnow()
        expired_session = await self.storage.save(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="已过期会话。",
                expires_at=now - timedelta(seconds=1),
            )
        )
        expired_working = await self.storage.save(
            self.memory(
                tier=MemoryTier.WORKING,
                content="已过期工作状态。",
                expires_at=now - timedelta(seconds=1),
            )
        )
        long_term = await self.storage.save(
            self.memory(
                tier=MemoryTier.LONG_TERM,
                content="长期证据不会自动淘汰。",
                expires_at=now - timedelta(seconds=1),
            )
        )
        future_working = await self.storage.save(
            self.memory(
                tier=MemoryTier.WORKING,
                content="仍有效的工作状态。",
                expires_at=now + timedelta(days=1),
            )
        )

        preview = await self.manager.sweep_lifecycle(
            user_id="user",
            novel_id="novel",
            now=now,
            dry_run=True,
        )
        self.assertEqual(preview.evicted_count, 2)
        self.assertIsNotNone(await self.storage.get(expired_session.id))

        mocked_remove = AsyncMock(return_value=True)
        with patch.object(
            manager_module.memory_indexer,
            "remove",
            new=mocked_remove,
        ):
            result = await self.manager.sweep_lifecycle(
                user_id="user",
                novel_id="novel",
                now=now,
            )

        self.assertEqual(
            set(result.evicted_memory_ids),
            {expired_session.id, expired_working.id},
        )
        self.assertIsNone(await self.storage.get(expired_session.id))
        self.assertIsNone(await self.storage.get(expired_working.id))
        self.assertIsNotNone(await self.storage.get(long_term.id))
        self.assertIsNotNone(await self.storage.get(future_working.id))
        self.assertEqual(mocked_remove.await_count, 2)

    async def test_close_session_is_scoped(self) -> None:

        first = await self.storage.save(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="会话 A。",
            )
        )
        second = await self.storage.save(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-b",
                content="会话 B。",
            )
        )

        with patch.object(
            manager_module.memory_indexer,
            "remove",
            new=AsyncMock(return_value=False),
        ):
            result = await self.manager.close_session(
                user_id="user",
                novel_id="novel",
                session_id="session-a",
            )

        self.assertEqual(result.evicted_memory_ids, [first.id])
        self.assertIsNone(await self.storage.get(first.id))
        self.assertIsNotNone(await self.storage.get(second.id))

    async def test_faiss_consistency_excludes_session_memory(self) -> None:

        session = await self.storage.save(
            self.memory(
                tier=MemoryTier.SESSION,
                session_id="session-a",
                content="不会进入向量索引。",
            )
        )
        long_term = await self.storage.save(
            self.memory(
                tier=MemoryTier.LONG_TERM,
                content="会进入向量索引。",
            )
        )

        service = MemoryIndexConsistencyService(db_path=self.db_path)
        rows = service._load_sqlite_memories()

        self.assertEqual(rows, [(long_term.id, long_term.content)])
        self.assertNotIn(session.id, {memory_id for memory_id, _ in rows})


class MemoryTieredContextTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:

        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp_directory.name) / "memory.db"
        )
        self.storage = SQLiteMemoryStorage(self.db_path)

    def tearDown(self) -> None:

        self.temp_directory.cleanup()

    async def test_context_orders_tiers_and_isolates_session(self) -> None:

        await self.storage.save(
            MemoryItem(
                user_id="user",
                novel_id="novel",
                memory_type=MemoryType.PLOT,
                memory_tier=MemoryTier.SESSION,
                session_id="current",
                content="当前只讨论潮钟。",
            )
        )
        await self.storage.save(
            MemoryItem(
                user_id="user",
                novel_id="novel",
                memory_type=MemoryType.PLOT,
                memory_tier=MemoryTier.SESSION,
                session_id="other",
                content="其它会话秘密。",
            )
        )

        indexed = [
            SimpleNamespace(
                memory_type="plot",
                memory_tier="working",
                content="本章需要确认坐标。",
            ),
            SimpleNamespace(
                memory_type="world",
                memory_tier="long_term",
                content="潮钟来自空白海域。",
            ),
        ]
        mocked_retrieve = AsyncMock(return_value=indexed)

        builder = MemoryContextBuilder(storage=self.storage)
        with patch.object(
            context_module.hybrid_memory_retriever,
            "retrieve",
            new=mocked_retrieve,
        ):
            result = await builder.build(
                user_id="user",
                novel_id="novel",
                query="潮钟",
                session_id="current",
            )

        self.assertIn("当前只讨论潮钟", result)
        self.assertNotIn("其它会话秘密", result)
        self.assertLess(
            result.index("Session Memory"),
            result.index("Working Memory"),
        )
        self.assertLess(
            result.index("Working Memory"),
            result.index("Long-term Memory"),
        )
        self.assertEqual(
            mocked_retrieve.await_args.kwargs["memory_tiers"],
            {"working", "long_term"},
        )


class MemoryExtractorRegressionTests(unittest.IsolatedAsyncioTestCase):

    async def test_each_extracted_fact_is_saved_once(self) -> None:

        extractor = MemoryExtractor()
        extractor.llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value={
                    "content": (
                        '[{"memory_type":"plot",'
                        '"content":"潮钟编号是 AMBER-17。",'
                        '"importance":0.9}]'
                    )
                }
            )
        )
        mocked_add = AsyncMock(side_effect=lambda memory: memory)

        with patch.object(
            extractor_module.memory_manager,
            "add_memory",
            new=mocked_add,
        ):
            result = await extractor.extract(
                user_id="user",
                novel_id="novel",
                query="潮钟编号是 AMBER-17。",
            )

        self.assertEqual(len(result), 1)
        mocked_add.assert_awaited_once()


class MemoryLifecycleApiTests(unittest.TestCase):

    def setUp(self) -> None:

        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp_directory.name) / "memory.db"
        )
        self.manager = MemoryManager(self.db_path)
        self.client = TestClient(app)

    def tearDown(self) -> None:

        self.client.close()
        self.temp_directory.cleanup()

    def test_api_create_promote_events_and_conflict(self) -> None:

        body = {
            "user_id": "user",
            "novel_id": "novel",
            "memory_type": "plot",
            "memory_tier": "session",
            "session_id": "session-a",
            "content": "当前复核潮钟坐标。",
            "importance": 0.8,
        }

        with (
            patch.object(
                memory_api_module,
                "memory_manager",
                self.manager,
            ),
            patch.object(
                manager_module.memory_indexer,
                "upsert_memory",
                new=AsyncMock(return_value=1),
            ),
        ):
            created = self.client.post("/api/v1/memory", json=body)
            memory_id = created.json()["data"]["id"]

            conflict = self.client.post(
                f"/api/v1/memory/{memory_id}/promote",
                json={
                    "expected_revision": 99,
                    "target_tier": "working",
                    "basis": "user_confirmed",
                    "reason": "错误 revision。",
                },
            )
            promoted = self.client.post(
                f"/api/v1/memory/{memory_id}/promote",
                json={
                    "expected_revision": 1,
                    "target_tier": "working",
                    "basis": "user_confirmed",
                    "reason": "用户确认当前任务。",
                },
            )
            events = self.client.get(
                f"/api/v1/memory/{memory_id}/lifecycle/events"
            )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(promoted.status_code, 200)
        self.assertEqual(
            promoted.json()["data"]["memory"]["memory_tier"],
            "working",
        )
        self.assertEqual(events.status_code, 200)
        self.assertEqual(len(events.json()["data"]), 2)

    def test_openapi_registers_lifecycle_routes(self) -> None:

        paths = app.openapi()["paths"]
        for path in {
            "/api/v1/memory/{memory_id}/promote",
            "/api/v1/memory/{memory_id}/lifecycle/events",
            "/api/v1/memory/lifecycle/sweep",
            "/api/v1/memory/sessions/{session_id}/close",
        }:
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
