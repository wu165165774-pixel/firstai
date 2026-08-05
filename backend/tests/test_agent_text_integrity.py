import unittest

from app.agents.bootstrap import (
    create_agent_manager,
)
from app.agents.novel_agent import NovelAgent


class AgentTextIntegrityTests(
    unittest.TestCase
):

    def test_system_prompt_is_not_corrupted(
        self,
    ) -> None:

        prompt = NovelAgent._system_prompt()

        self.assertIn(
            (
                "\u4f60\u662f NovelForge "
                "\u7684\u901a\u7528\u5c0f\u8bf4"
                "\u521b\u4f5c Agent\u3002"
            ),
            prompt,
        )

        self.assertNotIn(
            "?",
            prompt,
        )

        self.assertNotIn(
            "\ufffd",
            prompt,
        )

    def test_description_is_not_corrupted(
        self,
    ) -> None:

        agent = NovelAgent(
            llm_manager=object()
        )

        self.assertIn(
            (
                "\u901a\u7528\u5c0f\u8bf4"
                "\u4efb\u52a1 Agent"
            ),
            agent.description,
        )

        self.assertNotIn(
            "?",
            agent.description,
        )

    def test_bootstrap_docstring_is_not_corrupted(
        self,
    ) -> None:

        docstring = (
            create_agent_manager.__doc__
            or ""
        )

        self.assertIn(
            (
                "\u521b\u5efa NovelForge "
                "AgentManager"
            ),
            docstring,
        )

        self.assertNotIn(
            "?",
            docstring,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
