from __future__ import annotations

import unittest

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    patch,
)

from app.agents import novel_agent as novel_module
from app.agents.base import BaseAgent
from app.agents.errors import (
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
)
from app.agents.manager import AgentManager
from app.agents.novel_agent import NovelAgent
from app.agents.registry import AgentRegistry
from app.agents.schemas import (
    AgentContext,
    AgentResult,
)
from app.llm.schemas import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
)
from app.memory.context import MemoryContextBlock


class DummyAgent(BaseAgent):

    @property
    def name(self) -> str:

        return "dummy"

    @property
    def description(self) -> str:

        return "Dummy test agent."

    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:

        return AgentResult(
            agent=self.name,
            content=context.instruction,
            provider=context.provider,
            model=context.model or "test-model",
        )


class AgentRegistryTests(
    unittest.TestCase
):

    def test_register_and_get_agent(
        self,
    ) -> None:

        registry = AgentRegistry()

        agent = DummyAgent()

        registry.register(
            agent
        )

        self.assertTrue(
            registry.contains(
                "dummy"
            )
        )

        self.assertIs(
            registry.get(
                "DUMMY"
            ),
            agent,
        )

        self.assertEqual(
            registry.list(),
            [
                "dummy",
            ],
        )

    def test_duplicate_agent_is_rejected(
        self,
    ) -> None:

        registry = AgentRegistry()

        registry.register(
            DummyAgent()
        )

        with self.assertRaises(
            AgentAlreadyRegisteredError
        ):

            registry.register(
                DummyAgent()
            )

    def test_missing_agent_is_rejected(
        self,
    ) -> None:

        registry = AgentRegistry()

        with self.assertRaises(
            AgentNotFoundError
        ):

            registry.get(
                "missing"
            )


class AgentManagerTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_manager_executes_agent(
        self,
    ) -> None:

        registry = AgentRegistry()

        registry.register(
            DummyAgent()
        )

        manager = AgentManager(
            registry
        )

        result = await manager.execute(
            "dummy",
            {
                "user_id": "user001",
                "novel_id": "novel001",
                "instruction": "完成测试任务",
                "provider": "qwen_local",
                "model": "test-model",
            },
        )

        self.assertEqual(
            result.agent,
            "dummy",
        )

        self.assertEqual(
            result.content,
            "完成测试任务",
        )


class NovelAgentTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_novel_agent_exposes_memory_retrieval_diagnostics(
        self,
    ) -> None:

        response = ChatResponse(
            content="潮钟坐标仍待复核。",
            model="qwen3:8b",
            provider="qwen_local",
        )
        llm_manager = SimpleNamespace(
            chat=AsyncMock(return_value=response)
        )
        memory_context = MemoryContextBlock(
            "【Long-term Memory】\n- [plot] 潮钟坐标仍待复核。",
            mode="vector_only",
            degraded=True,
            lanes=[
                {"path": "vector", "status": "success"},
                {"path": "graph", "status": "unavailable"},
            ],
        )

        with patch.object(
            novel_module.memory_context_builder,
            "build",
            new=AsyncMock(return_value=memory_context),
        ):
            result = await NovelAgent(llm_manager).run(
                AgentContext(
                    user_id="user001",
                    novel_id="novel001",
                    instruction="潮钟状态是什么？",
                    use_canon=False,
                )
            )

        request = llm_manager.chat.await_args.args[1]
        self.assertEqual(
            request.metadata["memory_retrieval_mode"],
            "vector_only",
        )
        self.assertTrue(request.metadata["memory_retrieval_degraded"])
        self.assertEqual(
            result.metadata["memory_retrieval_lanes"][1]["status"],
            "unavailable",
        )

    async def test_novel_agent_injects_memory(
        self,
    ) -> None:

        response = ChatResponse(
            id="response-001",
            content="根据设定，林凡性格谨慎。",
            model="qwen3:8b",
            provider="qwen_local",
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
            ),
            latency_ms=100.0,
        )

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=response
            )
        )

        agent = NovelAgent(
            llm_manager=llm_manager
        )

        context = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction="林凡是什么性格？",
            provider="qwen_local",
            model="qwen3:8b",
        )

        mocked_memory = AsyncMock(
            return_value=(
                "【角色设定】\n"
                "- 林凡性格谨慎。"
            )
        )

        with patch.object(
            novel_module.memory_context_builder,
            "build",
            new=mocked_memory,
        ):

            result = await agent.run(
                context
            )

        mocked_memory.assert_awaited_once_with(
            user_id="user001",
            novel_id="novel001",
            query="林凡是什么性格？",
            top_k=4,
        )

        llm_manager.chat.assert_awaited_once()

        provider, request = (
            llm_manager.chat.await_args.args
        )

        self.assertEqual(
            provider,
            "qwen_local",
        )

        self.assertEqual(
            request.messages[-1].role,
            "user",
        )

        self.assertEqual(
            request.messages[-1].content,
            "林凡是什么性格？",
        )

        self.assertTrue(
            any(
                "林凡性格谨慎"
                in message.content
                for message
                in request.messages
            )
        )

        self.assertEqual(
            request.metadata["agent"],
            "novel",
        )

        self.assertEqual(
            result.agent,
            "novel",
        )

        self.assertEqual(
            result.content,
            "根据设定，林凡性格谨慎。",
        )

    async def test_memory_can_be_disabled(
        self,
    ) -> None:

        response = ChatResponse(
            content="测试回答",
            model="qwen3:8b",
            provider="qwen_local",
        )

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=response
            )
        )

        agent = NovelAgent(
            llm_manager=llm_manager
        )

        context = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction="生成一个测试句子。",
            use_memory=False,
        )

        mocked_memory = AsyncMock()

        with patch.object(
            novel_module.memory_context_builder,
            "build",
            new=mocked_memory,
        ):

            result = await agent.run(
                context
            )

        mocked_memory.assert_not_awaited()

        self.assertEqual(
            result.content,
            "测试回答",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
