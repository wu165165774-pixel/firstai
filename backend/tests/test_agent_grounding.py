from __future__ import annotations

import unittest

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    patch,
)

from app.agents.character_agent import (
    CharacterAgent,
)
from app.agents.grounding import (
    AgentGroundingService,
    GroundingMemory,
)
from app.agents.plot_agent import (
    PlotAgent,
)
from app.agents.schemas import (
    AgentContext,
)
from app.agents.world_agent import (
    WorldAgent,
)
from app.llm.schemas import (
    ChatResponse,
)


class AgentGroundingServiceTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_semantic_result_uses_memory_id(
        self,
    ) -> None:

        storage = SimpleNamespace()

        service = AgentGroundingService(
            storage=storage
        )

        candidate = SimpleNamespace(
            memory_id="memory-001",
            memory_type="character",
            content="\u6797\u51e1\u6027\u683c\u8c28\u614e\u3002",
            similarity=0.9,
            hybrid_score=0.8,
        )

        with patch(
            (
                "app.agents.grounding."
                "hybrid_memory_retriever.retrieve"
            ),
            new=AsyncMock(
                return_value=[
                    candidate,
                ]
            ),
        ):

            results = await service.retrieve(
                user_id="user001",
                novel_id="novel001",
                query="\u6797\u51e1\u662f\u4ec0\u4e48\u6027\u683c",
                allowed_memory_types={
                    "character",
                },
            )

        self.assertEqual(
            len(results),
            1,
        )

        self.assertEqual(
            results[0].id,
            "memory-001",
        )

    async def test_list_by_types_uses_sqlite_rows(
        self,
    ) -> None:

        world_row = SimpleNamespace(
            id="world-001",
            memory_type="world",
            content=(
                "\u9752\u4e91\u5b97"
                "\u4f4d\u4e8e"
                "\u4e1c\u8352\u5927\u9646\u3002"
            ),
        )

        storage = SimpleNamespace(
            query=AsyncMock(
                return_value=[
                    world_row,
                ]
            )
        )

        service = AgentGroundingService(
            storage=storage
        )

        results = await service.list_by_types(
            user_id="user001",
            novel_id="novel001",
            allowed_memory_types={
                "world",
            },
        )

        storage.query.assert_awaited_once_with(
            user_id="user001",
            novel_id="novel001",
            memory_type="world",
        )

        self.assertEqual(
            results[0].id,
            "world-001",
        )

        self.assertEqual(
            results[0].memory_type,
            "world",
        )


class AgentGroundingTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_world_list_uses_type_scan(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock()
        )

        agent = WorldAgent(
            llm_manager
        )

        request = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "\u6574\u7406\u5f53\u524d"
                "\u5df2\u7ecf\u786e\u8ba4\u7684"
                "\u4e16\u754c\u89c2\u8bbe\u5b9a"
            ),
            task_mode="grounded",
        )

        memories = [
            GroundingMemory(
                id="world-001",
                memory_type="world",
                content=(
                    "\u9752\u4e91\u5b97"
                    "\u4f4d\u4e8e"
                    "\u4e1c\u8352\u5927\u9646\u3002"
                ),
            )
        ]

        mocked_scan = AsyncMock(
            return_value=memories
        )

        with patch(
            (
                "app.agents.specialized_agent."
                "agent_grounding_service.list_by_types"
            ),
            new=mocked_scan,
        ):

            result = await agent.run(
                request
            )

        llm_manager.chat.assert_not_awaited()

        mocked_scan.assert_awaited_once()

        self.assertIn(
            "\u9752\u4e91\u5b97\u4f4d\u4e8e"
            "\u4e1c\u8352\u5927\u9646",
            result.content,
        )

        self.assertEqual(
            result.metadata[
                "retrieval_strategy"
            ],
            "sqlite_type_scan",
        )

        self.assertEqual(
            result.metadata[
                "memory_ids"
            ],
            [
                "world-001",
            ],
        )

    async def test_plot_without_memory_does_not_invent(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock()
        )

        agent = PlotAgent(
            llm_manager
        )

        request = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "\u68c0\u67e5\u5f53\u524d"
                "\u5267\u60c5\u8bb0\u5fc6"
                "\u662f\u5426\u5b58\u5728"
                "\u660e\u786e\u51b2\u7a81"
            ),
            task_mode="grounded",
        )

        with patch(
            (
                "app.agents.specialized_agent."
                "agent_grounding_service.list_by_types"
            ),
            new=AsyncMock(
                return_value=[]
            ),
        ):

            result = await agent.run(
                request
            )

        llm_manager.chat.assert_not_awaited()

        self.assertIn(
            "\u65e0\u6cd5\u5224\u65ad",
            result.content,
        )

        self.assertEqual(
            result.metadata["memory_count"],
            0,
        )

    async def test_character_single_fact_uses_one_evidence(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock()
        )

        agent = CharacterAgent(
            llm_manager
        )

        request = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "\u6797\u51e1"
                "\u662f\u4ec0\u4e48\u6027\u683c\uff1f"
            ),
            task_mode="auto",
        )

        memories = [
            GroundingMemory(
                id="character-001",
                memory_type="character",
                content=(
                    "\u6797\u51e1"
                    "\u6027\u683c\u8c28\u614e\u3002"
                ),
                similarity=0.9,
            ),
            GroundingMemory(
                id="character-002",
                memory_type="character",
                content=(
                    "\u82cf\u5a49"
                    "\u64c5\u957f\u4f7f\u7528"
                    "\u51b0\u7cfb\u6cd5\u672f\u3002"
                ),
                similarity=0.4,
            ),
        ]

        with patch(
            (
                "app.agents.specialized_agent."
                "agent_grounding_service.retrieve"
            ),
            new=AsyncMock(
                return_value=memories
            ),
        ):

            result = await agent.run(
                request
            )

        llm_manager.chat.assert_not_awaited()

        self.assertEqual(
            result.content,
            (
                "\u6839\u636e\u957f\u671f\u8bb0\u5fc6\uff0c"
                "\u6797\u51e1\u6027\u683c\u8c28\u614e\u3002"
            ),
        )

        self.assertEqual(
            result.metadata["memory_count"],
            1,
        )

        self.assertEqual(
            result.metadata["memory_ids"],
            [
                "character-001",
            ],
        )

        self.assertEqual(
            len(
                result.metadata["evidence"]
            ),
            1,
        )

    async def test_creative_mode_calls_llm(
        self,
    ) -> None:

        response = ChatResponse(
            content=(
                "\u8fd9\u662f\u4e00\u6761"
                "\u65b0\u7684\u521b\u4f5c\u5efa\u8bae\u3002"
            ),
            model="qwen3:8b",
            provider="qwen_local",
        )

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=response
            )
        )

        agent = WorldAgent(
            llm_manager
        )

        request = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "\u8bbe\u8ba1\u4e00\u4e2a"
                "\u65b0\u7684\u4fee\u70bc\u5b97\u95e8"
            ),
            task_mode="creative",
            use_memory=False,
        )

        result = await agent.run(
            request
        )

        llm_manager.chat.assert_awaited_once()

        self.assertTrue(
            result.metadata["llm_called"]
        )

        self.assertEqual(
            result.metadata["task_mode"],
            "creative",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
