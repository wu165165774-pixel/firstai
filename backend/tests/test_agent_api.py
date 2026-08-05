from __future__ import annotations

import unittest

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    patch,
)

from fastapi import HTTPException

from app.agents.bootstrap import (
    create_agent_manager,
)
from app.agents.character_agent import (
    CharacterAgent,
)
from app.agents.plot_agent import PlotAgent
from app.agents.schemas import (
    AgentContext,
    AgentResult,
)
from app.agents.world_agent import WorldAgent
from app.api.v1 import agents as agents_api


class SpecializedAgentTests(
    unittest.TestCase
):

    def setUp(self) -> None:

        self.llm_manager = SimpleNamespace()

    def test_character_agent_identity(
        self,
    ) -> None:

        agent = CharacterAgent(
            self.llm_manager
        )

        self.assertEqual(
            agent.name,
            "character",
        )

        self.assertIn(
            "\u4eba\u7269",
            agent.description,
        )

        self.assertNotIn(
            "?",
            agent._system_prompt(),
        )

    def test_world_agent_identity(
        self,
    ) -> None:

        agent = WorldAgent(
            self.llm_manager
        )

        self.assertEqual(
            agent.name,
            "world",
        )

        self.assertIn(
            "\u4e16\u754c",
            agent.description,
        )

        self.assertNotIn(
            "?",
            agent._system_prompt(),
        )

    def test_plot_agent_identity(
        self,
    ) -> None:

        agent = PlotAgent(
            self.llm_manager
        )

        self.assertEqual(
            agent.name,
            "plot",
        )

        self.assertIn(
            "\u5267\u60c5",
            agent.description,
        )

        self.assertNotIn(
            "?",
            agent._system_prompt(),
        )

    def test_bootstrap_registers_seven_agents(
        self,
    ) -> None:

        manager = create_agent_manager(
            self.llm_manager
        )

        self.assertEqual(
            manager.agents(),
            ["chapter", "character", "novel", "plot", "review", "rewrite", "world"],
        )


class AgentApiTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_list_agents(
        self,
    ) -> None:

        response = await agents_api.list_agents()

        names = [
            agent.name
            for agent in response.data.agents
        ]

        self.assertEqual(
            names,
            ["chapter", "character", "novel", "plot", "review", "rewrite", "world"],
        )

    async def test_execute_agent(
        self,
    ) -> None:

        expected = AgentResult(
            agent="character",
            content="\u4eba\u7269\u5206\u6790\u5b8c\u6210",
            provider="qwen_local",
            model="qwen3:8b",
        )

        mocked_execute = AsyncMock(
            return_value=expected
        )

        request = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction="\u5206\u6790\u6797\u51e1\u7684\u6027\u683c",
        )

        with patch.object(
            agents_api.agent_manager,
            "execute",
            new=mocked_execute,
        ):

            response = (
                await agents_api.execute_agent(
                    agent_name="character",
                    request=request,
                )
            )

        mocked_execute.assert_awaited_once_with(
            agent_name="character",
            context=request,
        )

        self.assertEqual(
            response.data.agent,
            "character",
        )

    async def test_missing_agent_returns_404(
        self,
    ) -> None:

        request = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction="\u6d4b\u8bd5\u4efb\u52a1",
        )

        with self.assertRaises(
            HTTPException
        ) as context:

            await agents_api.execute_agent(
                agent_name="missing",
                request=request,
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
