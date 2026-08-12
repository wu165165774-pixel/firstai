from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from app.agents.character_agent import CharacterAgent
from app.agents.grounding import (
    AgentGroundingService,
    GroundingMemory,
    GroundingRetrieval,
)
from app.agents.schemas import AgentContext
from app.api.v1 import chat as chat_module
from app.llm.schemas import ChatMessage, ChatRequest, ChatResponse
from app.main import app
from app.memory.context import MemoryContextBlock, MemoryContextBuilder
from app.retrieval.providers import (
    RetrievalCandidate,
    RetrievalPathUnavailable,
    VectorMemoryRetrievalProvider,
)
from app.retrieval.schemas import (
    DualRetrievalRequest,
    RetrievalLaneStatus,
    RetrievalPath,
)
from app.retrieval.service import DualPathRetriever


class FakeProvider:
    def __init__(
        self,
        path: RetrievalPath,
        candidates=None,
        *,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.path = path
        self.candidates = list(candidates or [])
        self.delay = delay
        self.error = error

    async def retrieve(self, request, candidate_k):
        del request, candidate_k
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return list(self.candidates)


class ConcurrentProbeProvider(FakeProvider):
    def __init__(self, path, state, candidates) -> None:
        super().__init__(path, candidates)
        self.state = state

    async def retrieve(self, request, candidate_k):
        del request, candidate_k
        self.state["started"] += 1
        if self.state["started"] == 2:
            self.state["both_started"].set()
        await asyncio.wait_for(self.state["both_started"].wait(), timeout=0.2)
        return list(self.candidates)


def candidate(
    path: RetrievalPath,
    source_id: str,
    content: str,
    score: float,
    *,
    evidence_type: str = "plot",
    metadata=None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        path=path,
        source_id=source_id,
        content=content,
        evidence_type=evidence_type,
        score=score,
        metadata=dict(metadata or {}),
    )


class DualPathRetrieverTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def request(**updates) -> DualRetrievalRequest:
        values = {
            "user_id": "user",
            "novel_id": "novel",
            "query": "潮钟在哪里",
            "top_k": 6,
            "char_budget": 2400,
            "timeout_ms": 500,
        }
        values.update(updates)
        return DualRetrievalRequest(**values)

    async def test_lanes_run_concurrently(self) -> None:
        state = {"started": 0, "both_started": asyncio.Event()}
        retriever = DualPathRetriever(
            vector_provider=ConcurrentProbeProvider(
                RetrievalPath.VECTOR,
                state,
                [candidate(RetrievalPath.VECTOR, "v1", "向量证据", 0.8)],
            ),
            graph_provider=ConcurrentProbeProvider(
                RetrievalPath.GRAPH,
                state,
                [candidate(RetrievalPath.GRAPH, "g1", "图证据", 0.9)],
            ),
        )
        result = await retriever.retrieve(self.request())

        self.assertEqual(state["started"], 2)
        self.assertEqual(result.mode, "dual")
        self.assertFalse(result.degraded)
        self.assertEqual(
            {lane.status for lane in result.lanes},
            {RetrievalLaneStatus.SUCCESS},
        )

    async def test_rrf_fuses_duplicate_content_and_keeps_provenance(self) -> None:
        retriever = DualPathRetriever(
            vector_provider=FakeProvider(
                RetrievalPath.VECTOR,
                [
                    candidate(
                        RetrievalPath.VECTOR,
                        "memory-1",
                        "潮钟位于北塔。",
                        0.82,
                        metadata={"memory_tier": "long_term"},
                    ),
                    candidate(RetrievalPath.VECTOR, "memory-2", "第二条", 0.7),
                ],
            ),
            graph_provider=FakeProvider(
                RetrievalPath.GRAPH,
                [
                    candidate(
                        RetrievalPath.GRAPH,
                        "event-1",
                        "  潮钟位于北塔。  ",
                        0.95,
                    ),
                    candidate(RetrievalPath.GRAPH, "event-2", "第三条", 0.8),
                ],
            ),
        )
        result = await retriever.retrieve(self.request())

        self.assertEqual(len(result.evidence), 3)
        self.assertEqual(result.deduplicated_count, 1)
        fused = result.evidence[0]
        self.assertEqual(
            set(fused.source_paths),
            {RetrievalPath.VECTOR, RetrievalPath.GRAPH},
        )
        self.assertEqual(
            {source.source_id for source in fused.sources},
            {"memory-1", "event-1"},
        )

    async def test_same_lane_duplicates_do_not_multiply_rrf_weight(self) -> None:
        duplicate_content = "同一事实"
        retriever = DualPathRetriever(
            vector_provider=FakeProvider(
                RetrievalPath.VECTOR,
                [
                    candidate(
                        RetrievalPath.VECTOR,
                        "memory-1",
                        duplicate_content,
                        0.9,
                    ),
                    candidate(
                        RetrievalPath.VECTOR,
                        "memory-2",
                        duplicate_content,
                        0.8,
                    ),
                ],
            ),
            graph_provider=FakeProvider(RetrievalPath.GRAPH),
        )

        result = await retriever.retrieve(self.request())

        self.assertEqual(result.deduplicated_count, 1)
        self.assertEqual(len(result.evidence[0].sources), 2)
        self.assertAlmostEqual(
            result.evidence[0].fusion_score,
            1.0 / (DualPathRetriever.RRF_K + 1),
        )

    async def test_budget_is_deterministic_and_bounded(self) -> None:
        retriever = DualPathRetriever(
            vector_provider=FakeProvider(
                RetrievalPath.VECTOR,
                [candidate(RetrievalPath.VECTOR, "v1", "甲" * 400, 0.9)],
            ),
            graph_provider=FakeProvider(
                RetrievalPath.GRAPH,
                [candidate(RetrievalPath.GRAPH, "g1", "乙" * 400, 0.8)],
            ),
        )
        request = self.request(char_budget=256)
        first = await retriever.retrieve(request)
        second = await retriever.retrieve(request)

        self.assertLessEqual(first.chars_used, 256)
        self.assertEqual(
            first.model_dump(exclude={"lanes"}),
            second.model_dump(exclude={"lanes"}),
        )
        self.assertTrue(first.truncated)

    async def test_graph_unavailable_degrades_to_vector(self) -> None:
        retriever = DualPathRetriever(
            vector_provider=FakeProvider(
                RetrievalPath.VECTOR,
                [candidate(RetrievalPath.VECTOR, "v1", "向量证据", 0.8)],
            ),
            graph_provider=FakeProvider(
                RetrievalPath.GRAPH,
                error=RetrievalPathUnavailable("not configured"),
            ),
        )
        result = await retriever.retrieve(self.request())

        self.assertEqual(result.mode, "vector_only")
        self.assertTrue(result.degraded)
        graph = next(lane for lane in result.lanes if lane.path == "graph")
        self.assertEqual(graph.status, RetrievalLaneStatus.UNAVAILABLE)
        self.assertEqual(len(result.evidence), 1)

    async def test_vector_failure_degrades_to_graph_without_leaking_error(self) -> None:
        retriever = DualPathRetriever(
            vector_provider=FakeProvider(
                RetrievalPath.VECTOR,
                error=RuntimeError("secret-token=abc"),
            ),
            graph_provider=FakeProvider(
                RetrievalPath.GRAPH,
                [candidate(RetrievalPath.GRAPH, "g1", "图证据", 0.9)],
            ),
        )
        result = await retriever.retrieve(self.request())

        self.assertEqual(result.mode, "graph_only")
        self.assertTrue(result.degraded)
        vector = next(lane for lane in result.lanes if lane.path == "vector")
        self.assertEqual(vector.status, RetrievalLaneStatus.FAILED)
        self.assertLessEqual(len(vector.error or ""), 500)
        self.assertNotIn("secret-token", vector.error or "")

    async def test_timed_out_lane_is_cancelled_and_other_lane_survives(self) -> None:
        retriever = DualPathRetriever(
            vector_provider=FakeProvider(
                RetrievalPath.VECTOR,
                [candidate(RetrievalPath.VECTOR, "v1", "向量证据", 0.8)],
            ),
            graph_provider=FakeProvider(
                RetrievalPath.GRAPH,
                delay=0.2,
            ),
        )
        result = await retriever.retrieve(self.request(timeout_ms=50))

        self.assertEqual(result.mode, "vector_only")
        graph = next(lane for lane in result.lanes if lane.path == "graph")
        self.assertEqual(graph.status, RetrievalLaneStatus.TIMED_OUT)


class RetrievalAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_exposes_memory_retrieval_diagnostics(self) -> None:
        memory_context = MemoryContextBlock(
            "【Long-term Memory】\n- [plot] 潮钟坐标仍待复核。",
            mode="vector_only",
            degraded=True,
            lanes=[
                {"path": "vector", "status": "success"},
                {"path": "graph", "status": "unavailable"},
            ],
        )
        response = ChatResponse(
            content="潮钟坐标仍待复核。",
            model="qwen3:8b",
            provider="qwen_local",
        )
        with (
            patch.object(
                chat_module.memory_context_builder,
                "build",
                new=AsyncMock(return_value=memory_context),
            ),
            patch.object(
                chat_module.llm_manager,
                "chat",
                new=AsyncMock(return_value=response),
            ),
        ):
            result = await chat_module.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(role="user", content="潮钟状态是什么？")
                    ],
                    metadata={"user_id": "u", "novel_id": "n"},
                ),
                BackgroundTasks(),
            )

        self.assertEqual(
            result.metadata["memory_retrieval_mode"],
            "vector_only",
        )
        self.assertTrue(result.metadata["memory_retrieval_degraded"])
        self.assertEqual(
            result.metadata["memory_retrieval_lanes"][1]["path"],
            "graph",
        )

    async def test_vector_adapter_keeps_scope_tiers_and_type_filter(self) -> None:
        raw = [
            SimpleNamespace(
                memory_id="m1",
                memory_type="plot",
                memory_tier="working",
                content="剧情证据",
                hybrid_score=0.8,
                similarity=0.9,
                importance=0.7,
            ),
            SimpleNamespace(
                memory_id="m2",
                memory_type="world",
                memory_tier="long_term",
                content="世界证据",
                hybrid_score=0.7,
                similarity=0.8,
                importance=0.6,
            ),
        ]
        with patch(
            "app.retrieval.providers.hybrid_memory_retriever.retrieve",
            new=AsyncMock(return_value=raw),
        ) as mocked:
            result = await VectorMemoryRetrievalProvider().retrieve(
                DualRetrievalRequest(
                    user_id="u",
                    novel_id="n",
                    query="q",
                    allowed_memory_types=["plot"],
                ),
                5,
            )

        self.assertEqual([item.source_id for item in result], ["m1"])
        mocked.assert_awaited_once()
        kwargs = mocked.await_args.kwargs
        self.assertEqual(kwargs["user_id"], "u")
        self.assertEqual(kwargs["novel_id"], "n")
        self.assertEqual(kwargs["memory_tiers"], {"working", "long_term"})

    async def test_agent_grounding_preserves_vector_memory_id(self) -> None:
        fused = SimpleNamespace(
            evidence_id="FUSED:abc",
            evidence_type="character",
            content="林凡性格谨慎。",
            fusion_score=0.03,
            source_paths=[RetrievalPath.VECTOR, RetrievalPath.GRAPH],
            sources=[
                SimpleNamespace(
                    path=RetrievalPath.VECTOR,
                    source_id="memory-001",
                    score=0.8,
                    metadata={"memory_tier": "long_term", "similarity": 0.9},
                ),
                SimpleNamespace(
                    path=RetrievalPath.GRAPH,
                    source_id="event-001",
                    score=0.9,
                    metadata={},
                ),
            ],
        )
        retrieval = SimpleNamespace(
            evidence=[fused],
            mode="dual",
            degraded=False,
            lanes=[],
        )
        with patch(
            "app.agents.grounding.dual_path_retriever.retrieve",
            new=AsyncMock(return_value=retrieval),
        ):
            result = await AgentGroundingService(
                storage=SimpleNamespace()
            ).retrieve("u", "n", "林凡是谁")

        self.assertEqual(result[0].id, "memory-001")
        self.assertEqual(result[0].source_paths, ("vector", "graph"))

    async def test_specialized_agent_exposes_lane_diagnostics(self) -> None:
        retrieval = GroundingRetrieval(
            memories=[
                GroundingMemory(
                    id="memory-001",
                    memory_type="character",
                    content="林凡性格谨慎。",
                    source_paths=("vector",),
                    fusion_score=0.02,
                )
            ],
            mode="vector_only",
            degraded=True,
            lanes=[
                {"path": "vector", "status": "success"},
                {"path": "graph", "status": "unavailable"},
            ],
        )
        with patch(
            "app.agents.specialized_agent."
            "agent_grounding_service.retrieve_with_diagnostics",
            new=AsyncMock(return_value=retrieval),
        ):
            result = await CharacterAgent(
                SimpleNamespace(chat=AsyncMock())
            ).run(
                AgentContext(
                    user_id="u",
                    novel_id="n",
                    instruction="林凡是什么性格？",
                    task_mode="grounded",
                )
            )

        self.assertEqual(result.metadata["retrieval_strategy"], "dual_path_fusion")
        self.assertEqual(result.metadata["retrieval_mode"], "vector_only")
        self.assertTrue(result.metadata["retrieval_degraded"])
        self.assertEqual(result.metadata["evidence"][0]["source_paths"], ["vector"])

    async def test_memory_context_keeps_session_and_graph_section(self) -> None:
        storage = SimpleNamespace(
            query=AsyncMock(
                return_value=[
                    SimpleNamespace(memory_type="plot", content="当前会话证据")
                ]
            )
        )
        evidence = [
            SimpleNamespace(
                content="工作记忆证据",
                evidence_type="plot",
                sources=[
                    SimpleNamespace(
                        path=RetrievalPath.VECTOR,
                        metadata={"memory_tier": "working"},
                    )
                ],
            ),
            SimpleNamespace(
                content="时间图证据",
                evidence_type="event",
                sources=[
                    SimpleNamespace(path=RetrievalPath.GRAPH, metadata={})
                ],
            ),
        ]
        with patch(
            "app.memory.context.dual_path_retriever.retrieve",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    evidence=evidence,
                    mode="dual",
                    degraded=False,
                    lanes=[],
                )
            ),
        ):
            result = await MemoryContextBuilder(storage=storage).build(
                user_id="u",
                novel_id="n",
                query="q",
                session_id="s",
            )

        self.assertIn("Session Memory", result)
        self.assertIn("Working Memory", result)
        self.assertIn("Temporal Graph", result)
        self.assertEqual(result.retrieval_mode, "dual")
        self.assertFalse(result.retrieval_degraded)
        self.assertLess(result.index("Session Memory"), result.index("Working Memory"))
        self.assertLess(
            result.index("【Working Memory｜"),
            result.index("【Temporal Graph｜"),
        )


class RetrievalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_fused_api_and_openapi(self) -> None:
        from app.api.v1 import retrieval as retrieval_api

        fake_response = {
            "mode": "vector_only",
            "degraded": True,
            "evidence": [],
            "lanes": [
                {
                    "path": "vector",
                    "status": "success",
                    "latency_ms": 1,
                    "candidate_count": 0,
                },
                {
                    "path": "graph",
                    "status": "unavailable",
                    "latency_ms": 1,
                    "candidate_count": 0,
                    "error": "not configured",
                },
            ],
            "char_budget": 2400,
            "chars_used": 0,
            "truncated": False,
            "deduplicated_count": 0,
        }
        with patch.object(
            retrieval_api.dual_path_retriever,
            "retrieve",
            new=AsyncMock(return_value=fake_response),
        ):
            response = self.client.post(
                "/api/v1/retrieval/fused",
                json={"user_id": "u", "novel_id": "n", "query": "q"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["degraded"])
        self.assertIn("/api/v1/retrieval/fused", app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
