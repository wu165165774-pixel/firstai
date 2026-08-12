from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.novel_agent import NovelAgent
from app.agents.schemas import AgentContext
from app.api.v1 import external_knowledge as knowledge_api_module
from app.api.v1 import chat as chat_api_module
from app.knowledge.context import ExternalKnowledgeContextBuilder
from app.knowledge.manager import ExternalKnowledgeManager
from app.knowledge.schemas import (
    ExternalKnowledgeHit,
    ExternalKnowledgeCitation,
    ExternalKnowledgeRetrieveRequest,
    ExternalKnowledgeSourceCreate,
    ExternalKnowledgeSourceUpdate,
)
from app.knowledge.storage import (
    ExternalKnowledgeConflictError,
    SQLiteExternalKnowledgeStorage,
)
from app.llm.schemas import ChatMessage, ChatRequest, ChatResponse
from app.main import app
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.rag.faiss_store import PersistentFaissStore


class FakeExternalKnowledgeIndexer:
    def __init__(self) -> None:
        self.vectors: dict[str, str] = {}
        self.rebuild_count = 0

    async def upsert_chunks(self, chunks) -> int:
        prepared = list(chunks)
        self.vectors.update(dict(prepared))
        return len(prepared)

    async def remove_chunks(self, chunk_ids) -> int:
        removed = 0
        for chunk_id in chunk_ids:
            if self.vectors.pop(str(chunk_id), None) is not None:
                removed += 1
        return removed

    async def search(self, query: str, top_k: int):
        del query
        return [
            SimpleNamespace(
                chunk_id=chunk_id,
                similarity=max(0.99 - index * 0.01, 0.5),
            )
            for index, chunk_id in enumerate(self.vectors)
        ][:top_k]

    async def rebuild(self, chunks) -> int:
        self.vectors = dict(chunks)
        self.rebuild_count += 1
        return len(self.vectors)

    def stats(self):
        return {"count": len(self.vectors)}

    def list_chunk_ids(self):
        return list(self.vectors)


class ExternalKnowledgeSchemaTests(unittest.TestCase):
    def test_retrieve_scope_is_required_and_deduplicated(self) -> None:
        request = ExternalKnowledgeRetrieveRequest(
            user_id="user",
            knowledge_base_ids=["research", "research", "history"],
            query="潮汐周期",
        )
        self.assertEqual(
            request.knowledge_base_ids,
            ["research", "history"],
        )

        with self.assertRaises(ValidationError):
            ExternalKnowledgeRetrieveRequest(
                user_id="user",
                knowledge_base_ids=[],
                query="潮汐周期",
            )

    def test_update_requires_an_actual_change(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalKnowledgeSourceUpdate(
                user_id="user",
                knowledge_base_id="research",
                expected_revision=1,
            )


class ExternalKnowledgeStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.db_path = str(root / "external_knowledge.db")
        self.memory_db_path = str(root / "memory.db")
        self.storage = SQLiteExternalKnowledgeStorage(self.db_path)
        self.indexer = FakeExternalKnowledgeIndexer()
        self.manager = ExternalKnowledgeManager(
            storage=self.storage,
            indexer=self.indexer,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    @staticmethod
    def payload(
        *,
        user_id: str = "user-a",
        knowledge_base_id: str = "research",
        source_uri: str = "https://example.test/tides",
        content: str = "潮汐受到月球引力和海盆形态共同影响。",
    ) -> ExternalKnowledgeSourceCreate:
        return ExternalKnowledgeSourceCreate(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            source_type="paper",
            title="潮汐动力学资料",
            source_uri=source_uri,
            content=content,
            author="研究者甲",
            published_at="2026-01-15",
            metadata={"license": "CC-BY-4.0"},
        )

    async def test_database_and_vector_namespaces_are_physical_isolated(
        self,
    ) -> None:
        SQLiteMemoryStorage(self.memory_db_path)

        def tables(path: str) -> set[str]:
            with sqlite3.connect(path) as conn:
                return {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }

        memory_tables = tables(self.memory_db_path)
        knowledge_tables = tables(self.db_path)
        self.assertIn("memories", memory_tables)
        self.assertNotIn("external_knowledge_sources", memory_tables)
        self.assertNotIn("memories", knowledge_tables)
        self.assertEqual(
            {
                "external_knowledge_sources",
                "external_knowledge_revisions",
                "external_knowledge_chunks",
            },
            knowledge_tables,
        )

        root = Path(self.temp_directory.name) / "vectors"
        memory_store = PersistentFaissStore(
            index_dir=str(root),
            dimension=3,
        )
        external_store = PersistentFaissStore(
            index_dir=str(root),
            dimension=3,
            index_name="external_knowledge",
        )
        self.assertNotEqual(memory_store.index_path, external_store.index_path)
        self.assertEqual(memory_store.index_path.name, "memory.index")
        self.assertEqual(
            external_store.index_path.name,
            "external_knowledge.index",
        )
        self.assertEqual(
            memory_store.upsert_many(
                ["memory-a", "memory-b"],
                np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    dtype=np.float32,
                ),
            ),
            2,
        )
        self.assertEqual(
            set(memory_store.list_memory_ids()),
            {"memory-a", "memory-b"},
        )
        self.assertEqual(external_store.list_memory_ids(), [])

    async def test_chunking_is_deterministic_bounded_and_traceable(self) -> None:
        content = "甲" * 2250
        chunks = self.manager.chunk_content(content)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(
            all(len(chunk) <= self.manager.CHUNK_CHAR_BUDGET for chunk, _, _ in chunks)
        )
        self.assertEqual(chunks[0][1:], (0, 1000))
        self.assertEqual(chunks[1][1], 880)
        for chunk, start, end in chunks:
            self.assertEqual(content[start:end], chunk)

    async def test_create_and_duplicate_uri_conflict(self) -> None:
        result = await self.manager.create_source(self.payload())
        self.assertEqual(result.source.current_revision, 1)
        self.assertEqual(result.chunk_count, 1)
        self.assertTrue(result.indexed)
        self.assertEqual(len(self.indexer.vectors), 1)

        with self.assertRaises(ExternalKnowledgeConflictError):
            await self.manager.create_source(self.payload(content="另一版本"))

    async def test_scope_isolation_blocks_cross_user_and_base_reads(self) -> None:
        result = await self.manager.create_source(self.payload())
        source_id = result.source.source_id

        self.assertIsNone(
            await self.storage.get(source_id, "user-b", "research")
        )
        self.assertIsNone(
            await self.storage.get(source_id, "user-a", "other-base")
        )
        self.assertEqual(
            await self.storage.list_sources("user-b", "research"),
            [],
        )

    async def test_update_is_revisioned_and_conflict_guarded(self) -> None:
        created = await self.manager.create_source(self.payload())
        source_id = created.source.source_id
        old_chunk_ids = set(self.indexer.vectors)

        updated = await self.manager.update_source(
            source_id,
            ExternalKnowledgeSourceUpdate(
                user_id="user-a",
                knowledge_base_id="research",
                expected_revision=1,
                title="潮汐动力学资料（修订）",
                content="月球引力、太阳引力与海盆共振共同影响潮汐。",
            ),
        )
        self.assertEqual(updated.source.current_revision, 2)
        self.assertFalse(old_chunk_ids & set(self.indexer.vectors))
        revisions = await self.storage.list_revisions(
            source_id,
            "user-a",
            "research",
        )
        self.assertEqual([item.revision for item in revisions], [2, 1])
        self.assertIn("月球引力和海盆", revisions[1].content)

        with self.assertRaises(ExternalKnowledgeConflictError):
            await self.manager.update_source(
                source_id,
                ExternalKnowledgeSourceUpdate(
                    user_id="user-a",
                    knowledge_base_id="research",
                    expected_revision=1,
                    title="过期更新",
                ),
            )

    async def test_retrieve_returns_current_revision_citation_and_scope(
        self,
    ) -> None:
        target = await self.manager.create_source(self.payload())
        await self.manager.create_source(
            self.payload(
                knowledge_base_id="private",
                source_uri="https://example.test/private",
                content="不应跨知识库召回的内容。",
            )
        )
        await self.manager.create_source(
            self.payload(
                user_id="user-b",
                source_uri="https://example.test/other-user",
                content="不应跨用户召回的内容。",
            )
        )

        hits = await self.manager.retrieve(
            ExternalKnowledgeRetrieveRequest(
                user_id="user-a",
                knowledge_base_ids=["research"],
                query="月球与潮汐",
            )
        )
        self.assertEqual(len(hits), 1)
        citation = hits[0].citation
        self.assertEqual(citation.source_id, target.source.source_id)
        self.assertEqual(citation.source_revision, 1)
        self.assertEqual(citation.knowledge_base_id, "research")
        self.assertEqual(citation.source_uri, "https://example.test/tides")
        self.assertTrue(citation.citation_id.startswith("EK:"))
        self.assertEqual(
            target.source.content[citation.start_char : citation.end_char],
            hits[0].content,
        )

    async def test_delete_cascades_revisions_chunks_and_vectors(self) -> None:
        created = await self.manager.create_source(self.payload())
        source_id = created.source.source_id
        await self.manager.update_source(
            source_id,
            ExternalKnowledgeSourceUpdate(
                user_id="user-a",
                knowledge_base_id="research",
                expected_revision=1,
                content="修订后的潮汐资料。",
            ),
        )

        deleted = await self.manager.delete_source(
            source_id,
            "user-a",
            "research",
        )
        self.assertEqual(deleted.deleted_revision_count, 2)
        self.assertEqual(deleted.deleted_chunk_count, 2)
        self.assertEqual(deleted.removed_vector_count, 1)
        self.assertEqual(self.indexer.vectors, {})
        self.assertIsNone(
            await self.storage.get(source_id, "user-a", "research")
        )

    async def test_consistency_rebuild_uses_only_current_chunks(self) -> None:
        created = await self.manager.create_source(self.payload())
        await self.manager.update_source(
            created.source.source_id,
            ExternalKnowledgeSourceUpdate(
                user_id="user-a",
                knowledge_base_id="research",
                expected_revision=1,
                content="当前 revision 的唯一索引内容。",
            ),
        )
        current_ids = {
            chunk_id
            for chunk_id, _ in await self.storage.list_current_chunks()
        }
        self.indexer.vectors = {"orphan": "旧向量"}

        status = await self.manager.check_and_repair_index()
        self.assertTrue(status.consistent)
        self.assertTrue(status.rebuilt)
        self.assertEqual(status.orphaned_in_faiss, ["orphan"])
        self.assertEqual(set(self.indexer.vectors), current_ids)
        self.assertEqual(self.indexer.rebuild_count, 1)


class ExternalKnowledgeContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_is_bounded_cited_and_marks_p6_boundary(self) -> None:
        citation = ExternalKnowledgeCitation(
            citation_id="EK:source-1:r2:c1",
            source_id="source-1",
            source_revision=2,
            chunk_id="chunk-1",
            chunk_number=1,
            start_char=0,
            end_char=4000,
            knowledge_base_id="research",
            source_type="paper",
            title="海洋资料",
            source_uri="https://example.test/ocean",
        )
        manager = SimpleNamespace(
            retrieve=AsyncMock(
                return_value=[
                    ExternalKnowledgeHit(
                        content="潮汐证据。" * 1000,
                        similarity=0.91,
                        citation=citation,
                    )
                ]
            )
        )
        builder = ExternalKnowledgeContextBuilder(manager=manager)
        result = await builder.build(
            user_id="user",
            knowledge_base_ids=["research"],
            query="潮汐",
        )

        self.assertLessEqual(len(result), builder.CONTEXT_CHAR_BUDGET)
        self.assertIn("P6 外部世界知识证据", result)
        self.assertIn("不是小说 Canon", result)
        self.assertIn("[EK:source-1:r2:c1]", result)
        self.assertIn("https://example.test/ocean", result)


class ExternalKnowledgeAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_requires_explicit_base_and_orders_external_last(
        self,
    ) -> None:
        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="港口资料。[EK:s] [EK:forged:r9:c9]",
                    provider="qwen_local",
                    model="qwen3:8b",
                )
            )
        )
        agent = NovelAgent(llm_manager)
        context = AgentContext(
            user_id="user",
            novel_id="novel",
            instruction="参考航海史设计港口",
            external_knowledge_base_ids=["research"],
            messages=[
                ChatMessage(
                    role="system",
                    content="[PLAN] chapter",
                    metadata={"source": "chapter_plan_grounding"},
                )
            ],
        )

        with (
            patch(
                "app.agents.novel_agent.canon_context_builder.build",
                new=AsyncMock(return_value="[CANON] facts"),
            ),
            patch(
                "app.agents.novel_agent.memory_context_builder.build",
                new=AsyncMock(return_value="[MEMORY] evidence"),
            ),
            patch(
                "app.agents.novel_agent.external_knowledge_context_builder.build",
                new=AsyncMock(return_value="[EXTERNAL] [EK:s:r1:c1]"),
            ) as external_build,
        ):
            result = await agent.run(context)

        request = llm_manager.chat.await_args.args[1]
        sources = [
            message.metadata.get("source")
            for message in request.messages
            if message.metadata.get("source")
        ]
        self.assertEqual(
            sources[:4],
            [
                "canonical_entity_registry",
                "chapter_plan_grounding",
                "long_term_memory",
                "external_knowledge",
            ],
        )
        external_build.assert_awaited_once()
        external_message = next(
            message
            for message in request.messages
            if message.metadata.get("source") == "external_knowledge"
        )
        self.assertEqual(external_message.metadata["priority"], "P6")
        self.assertTrue(external_message.metadata["citation_required"])
        request = llm_manager.chat.await_args.args[1]
        self.assertTrue(request.metadata["external_knowledge_used"])
        self.assertEqual(result.content, "港口资料。[EK:s:r1:c1]")
        self.assertEqual(
            result.metadata["external_knowledge_citations"],
            ["EK:s:r1:c1"],
        )

    async def test_agent_does_not_query_external_knowledge_by_default(
        self,
    ) -> None:
        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="done",
                    provider="qwen_local",
                    model="qwen3:8b",
                )
            )
        )
        agent = NovelAgent(llm_manager)
        external_build = AsyncMock(return_value="unexpected")
        with (
            patch(
                "app.agents.novel_agent.canon_context_builder.build",
                new=AsyncMock(return_value=""),
            ),
            patch(
                "app.agents.novel_agent.memory_context_builder.build",
                new=AsyncMock(return_value=""),
            ),
            patch(
                "app.agents.novel_agent.external_knowledge_context_builder.build",
                new=external_build,
            ),
        ):
            await agent.run(
                AgentContext(
                    user_id="user",
                    novel_id="novel",
                    instruction="继续写作",
                )
            )
        external_build.assert_not_awaited()

    async def test_external_chat_does_not_auto_extract_into_novel_memory(
        self,
    ) -> None:
        background_tasks = BackgroundTasks()
        request = ChatRequest(
            provider="qwen_local",
            model="qwen3:8b",
            messages=[ChatMessage(role="user", content="潮汐如何形成？")],
            metadata={
                "user_id": "user",
                "novel_id": "novel",
                "external_knowledge_base_ids": ["research"],
            },
        )
        with (
            patch.object(
                chat_api_module.memory_context_builder,
                "build",
                new=AsyncMock(return_value=""),
            ),
            patch.object(
                chat_api_module.external_knowledge_context_builder,
                "build",
                new=AsyncMock(return_value="[EXTERNAL] [EK:s:r1:c1]"),
            ),
            patch.object(
                chat_api_module.llm_manager,
                "chat",
                new=AsyncMock(
                    return_value=ChatResponse(
                        content="月球引力。",
                        provider="qwen_local",
                        model="qwen3:8b",
                    )
                ),
            ),
        ):
            result = await chat_api_module.chat(request, background_tasks)

        self.assertEqual(background_tasks.tasks, [])
        self.assertTrue(result.metadata["external_knowledge_used"])
        self.assertTrue(result.metadata["memory_extraction_skipped"])
        self.assertEqual(
            result.content,
            "月球引力。\n\n来源：[EK:s:r1:c1]",
        )
        self.assertEqual(
            result.metadata["external_knowledge_citations"],
            ["EK:s:r1:c1"],
        )


class ExternalKnowledgeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        storage = SQLiteExternalKnowledgeStorage(
            str(Path(self.temp_directory.name) / "external.db")
        )
        self.manager = ExternalKnowledgeManager(
            storage=storage,
            indexer=FakeExternalKnowledgeIndexer(),
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_directory.cleanup()

    def test_api_revision_conflict_retrieve_and_delete(self) -> None:
        body = {
            "user_id": "user",
            "knowledge_base_id": "research",
            "source_type": "web",
            "title": "港口史",
            "source_uri": "https://example.test/port",
            "content": "石砌防波堤会改变港内波浪传播。",
        }
        with patch.object(
            knowledge_api_module,
            "external_knowledge_manager",
            self.manager,
        ):
            created = self.client.post(
                "/api/v1/external-knowledge/sources",
                json=body,
            )
            self.assertEqual(created.status_code, 201)
            source_id = created.json()["data"]["source"]["source_id"]

            cross_scope = self.client.get(
                f"/api/v1/external-knowledge/sources/{source_id}",
                params={
                    "user_id": "other",
                    "knowledge_base_id": "research",
                },
            )
            self.assertEqual(cross_scope.status_code, 404)

            update_body = {
                "user_id": "user",
                "knowledge_base_id": "research",
                "expected_revision": 1,
                "content": "修订：石砌防波堤会改变波浪传播与沉积。",
            }
            updated = self.client.put(
                f"/api/v1/external-knowledge/sources/{source_id}",
                json=update_body,
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(
                updated.json()["data"]["source"]["current_revision"],
                2,
            )
            stale = self.client.put(
                f"/api/v1/external-knowledge/sources/{source_id}",
                json=update_body,
            )
            self.assertEqual(stale.status_code, 409)

            revisions = self.client.get(
                f"/api/v1/external-knowledge/sources/{source_id}/revisions",
                params={
                    "user_id": "user",
                    "knowledge_base_id": "research",
                },
            )
            self.assertEqual(revisions.status_code, 200)
            self.assertEqual(
                [item["revision"] for item in revisions.json()["data"]],
                [2, 1],
            )

            retrieved = self.client.post(
                "/api/v1/external-knowledge/retrieve",
                json={
                    "user_id": "user",
                    "knowledge_base_ids": ["research"],
                    "query": "防波堤",
                },
            )
            self.assertEqual(retrieved.status_code, 200)
            self.assertEqual(len(retrieved.json()["data"]), 1)
            self.assertEqual(
                retrieved.json()["data"][0]["citation"]["source_revision"],
                2,
            )

            deleted = self.client.delete(
                f"/api/v1/external-knowledge/sources/{source_id}",
                params={
                    "user_id": "user",
                    "knowledge_base_id": "research",
                },
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(
                deleted.json()["data"]["deleted_revision_count"],
                2,
            )

    def test_openapi_registers_external_knowledge_operations(self) -> None:
        schema = app.openapi()
        paths = schema["paths"]
        expected = {
            "/api/v1/external-knowledge/sources": {"get", "post"},
            "/api/v1/external-knowledge/sources/{source_id}": {
                "get",
                "put",
                "delete",
            },
            "/api/v1/external-knowledge/sources/{source_id}/revisions": {
                "get"
            },
            "/api/v1/external-knowledge/retrieve": {"post"},
        }
        for path, methods in expected.items():
            self.assertIn(path, paths)
            self.assertEqual(set(paths[path]), methods)


if __name__ == "__main__":
    unittest.main()
