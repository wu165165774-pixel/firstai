from __future__ import annotations

import unittest

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
)

from app.agents.bootstrap import (
    create_agent_registry,
)
from app.agents.chapter_agent import (
    ChapterAgent,
)
from app.agents.review_agent import (
    ReviewAgent,
)
from app.agents.rewrite_agent import (
    RewriteAgent,
)
from app.agents.schemas import (
    AgentContext,
)
from app.llm.schemas import (
    ChatResponse,
)


class AdvancedAgentIdentityTests(
    unittest.TestCase
):

    def setUp(self) -> None:

        self.llm_manager = SimpleNamespace(
            chat=AsyncMock()
        )

    def test_chapter_agent_identity(
        self,
    ) -> None:

        agent = ChapterAgent(
            self.llm_manager
        )

        self.assertEqual(
            agent.name,
            "chapter",
        )

        self.assertEqual(
            agent.execution_mode,
            "chapter_generation",
        )

        self.assertEqual(
            agent.recommended_reasoning_effort,
            "low",
        )

        self.assertIn(
            "complete novel chapter",
            agent._system_prompt(),
        )

    def test_rewrite_agent_identity(
        self,
    ) -> None:

        agent = RewriteAgent(
            self.llm_manager
        )

        self.assertEqual(
            agent.name,
            "rewrite",
        )

        self.assertEqual(
            agent.execution_mode,
            "text_rewrite",
        )

        self.assertEqual(
            agent.recommended_reasoning_effort,
            "none",
        )

        self.assertIn(
            "rewritten text",
            agent._system_prompt(),
        )

    def test_review_agent_identity(
        self,
    ) -> None:

        agent = ReviewAgent(
            self.llm_manager
        )

        self.assertEqual(
            agent.name,
            "review",
        )

        self.assertEqual(
            agent.execution_mode,
            "content_review",
        )

        self.assertEqual(
            agent.recommended_reasoning_effort,
            "medium",
        )

        self.assertIn(
            "confirmed conflicts",
            agent._system_prompt(),
        )

        self.assertIn(
            "Never resolve an unsupported statement",
            agent._system_prompt(),
        )

        self.assertIn(
            "classify it as unconfirmed",
            agent._system_prompt(),
        )

    def test_registry_contains_seven_agents(
        self,
    ) -> None:

        registry = create_agent_registry(
            self.llm_manager
        )

        self.assertEqual(
            set(
                registry.list()
            ),
            {
                "character",
                "chapter",
                "novel",
                "plot",
                "review",
                "rewrite",
                "world",
            },
        )


class AdvancedAgentExecutionTests(
    unittest.IsolatedAsyncioTestCase
):

    @staticmethod
    def _response(
        content: str,
        reasoning_effort: str,
    ) -> ChatResponse:

        return ChatResponse(
            content=content,
            model="qwen3:8b",
            provider="qwen_local",
            finish_reason="stop",
            metadata={
                "reasoning_effort": (
                    reasoning_effort
                ),
                "thinking_enabled": (
                    reasoning_effort
                    != "none"
                ),
            },
        )

    async def test_chapter_agent_executes_llm(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=self._response(
                    content="chapter text",
                    reasoning_effort="low",
                )
            )
        )

        agent = ChapterAgent(
            llm_manager
        )

        context = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction="Write chapter one.",
            use_memory=False,
            reasoning_effort="low",
        )

        result = await agent.run(
            context
        )

        called_request = (
            llm_manager
            .chat
            .await_args
            .args[1]
        )

        self.assertEqual(
            result.content,
            "chapter text",
        )

        self.assertEqual(
            result.metadata[
                "execution_mode"
            ],
            "chapter_generation",
        )

        self.assertTrue(
            result.metadata[
                "llm_called"
            ]
        )

        self.assertEqual(
            called_request.reasoning_effort,
            "low",
        )

        self.assertIn(
            "complete novel chapter",
            called_request
            .messages[0]
            .content,
        )

    async def test_rewrite_agent_executes_llm(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=self._response(
                    content="rewritten text",
                    reasoning_effort="none",
                )
            )
        )

        agent = RewriteAgent(
            llm_manager
        )

        context = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "Rewrite the supplied paragraph."
            ),
            use_memory=False,
            reasoning_effort="none",
        )

        result = await agent.run(
            context
        )

        self.assertEqual(
            result.metadata[
                "execution_mode"
            ],
            "text_rewrite",
        )

        self.assertEqual(
            result.metadata[
                "recommended_reasoning_effort"
            ],
            "none",
        )

        self.assertEqual(
            result.content,
            "rewritten text",
        )

    async def test_review_agent_executes_llm(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=self._response(
                    content="review result",
                    reasoning_effort="medium",
                )
            )
        )

        agent = ReviewAgent(
            llm_manager
        )

        context = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "Review this chapter for "
                "timeline conflicts."
            ),
            use_memory=False,
            reasoning_effort="medium",
        )

        result = await agent.run(
            context
        )

        called_request = (
            llm_manager
            .chat
            .await_args
            .args[1]
        )

        self.assertEqual(
            result.metadata[
                "execution_mode"
            ],
            "content_review",
        )

        self.assertEqual(
            result.metadata[
                "recommended_reasoning_effort"
            ],
            "medium",
        )

        self.assertEqual(
            called_request.reasoning_effort,
            "medium",
        )

        self.assertEqual(
            result.content,
            "review result",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
