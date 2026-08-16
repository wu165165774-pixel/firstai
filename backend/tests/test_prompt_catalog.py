import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.agents.chapter_agent import ChapterAgent
from app.agents.novel_agent import NovelAgent
from app.agents.schemas import AgentContext
from app.llm.schemas import ChatMessage, ChatResponse
from app.main import app
from app.prompts.bootstrap import prompt_registry
from app.prompts.registry import (
    PromptRegistry,
    PromptRevisionNotFoundError,
)


class PromptRegistryTests(unittest.TestCase):
    def test_revision_selection_is_explicit_and_deterministic(self) -> None:
        registry = PromptRegistry()
        registry.register(
            prompt_id="test.prompt",
            revision=1,
            category="agent",
            description="Revision one.",
            current=False,
        )
        registry.register(
            prompt_id="test.prompt",
            revision=2,
            category="agent",
            description="Revision two.",
        )
        descriptor = registry.list()[0]
        self.assertEqual(descriptor.current_revision, 2)
        self.assertEqual(descriptor.available_revisions, [1, 2])
        self.assertEqual(registry.select("test.prompt", 1).revision, 1)
        with self.assertRaises(PromptRevisionNotFoundError):
            registry.select("test.prompt", 3)

    def test_provenance_hashes_rendered_content_without_exposing_it(self) -> None:
        first = prompt_registry.provenance(
            "agent.novel.system",
            "private rendered prompt",
        )
        repeated = prompt_registry.provenance(
            "agent.novel.system",
            "private rendered prompt",
        )
        changed = prompt_registry.provenance(
            "agent.novel.system",
            "different prompt",
        )
        self.assertEqual(first.rendered_sha256, repeated.rendered_sha256)
        self.assertNotEqual(first.rendered_sha256, changed.rendered_sha256)
        self.assertNotIn("private rendered prompt", str(first.model_dump()))

    def test_request_digest_matches_provider_visible_messages(self) -> None:
        first = prompt_registry.request_provenance(
            "agent.novel.request",
            [
                ChatMessage(
                    role="system",
                    content="rules",
                    metadata={"not_sent": "one"},
                ),
                ChatMessage(role="user", content="write"),
            ],
        )
        second = prompt_registry.request_provenance(
            "agent.novel.request",
            [
                ChatMessage(
                    role="system",
                    content="rules",
                    metadata={"not_sent": "two"},
                ),
                ChatMessage(role="user", content="write"),
            ],
        )
        self.assertEqual(first.rendered_sha256, second.rendered_sha256)


class PromptCatalogApiTests(unittest.TestCase):
    def test_catalog_and_openapi_do_not_expose_prompt_content(self) -> None:
        response = TestClient(app).get("/api/v1/prompts")
        self.assertEqual(response.status_code, 200)
        prompts = response.json()["data"]["prompts"]
        self.assertEqual(len(prompts), 20)
        self.assertEqual(
            [item["prompt_id"] for item in prompts],
            sorted(item["prompt_id"] for item in prompts),
        )
        self.assertIn(
            "agent.planner.request",
            {item["prompt_id"] for item in prompts},
        )
        self.assertNotIn("content", response.text.lower())
        self.assertIn("/api/v1/prompts", app.openapi()["paths"])


class PromptAgentProvenanceTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, agent_class, name: str) -> None:
        response = ChatResponse(
            content="ok",
            model="test-model",
            provider="test-provider",
            metadata={
                "prompt_provenance": [
                    {"prompt_id": "forged"},
                ]
            },
        )
        manager = SimpleNamespace(chat=AsyncMock(return_value=response))
        result = await agent_class(manager).run(
            AgentContext(
                user_id="prompt-user",
                novel_id="prompt-novel",
                instruction="Generate content.",
                provider="test-provider",
                use_memory=False,
                use_canon=False,
                metadata={
                    "prompt_provenance": [
                        {"prompt_id": "client-forged"},
                    ]
                },
            )
        )
        request = manager.chat.await_args.args[1]
        expected_ids = [
            f"agent.{name}.system",
            f"agent.{name}.request",
        ]
        request_provenance = request.metadata["prompt_provenance"]
        result_provenance = result.metadata["prompt_provenance"]
        self.assertEqual(
            [item["prompt_id"] for item in request_provenance],
            expected_ids,
        )
        self.assertEqual(result_provenance, request_provenance)
        self.assertEqual(
            request_provenance[1],
            prompt_registry.request_provenance(
                f"agent.{name}.request",
                request.messages,
            ).model_dump(),
        )

    async def test_novel_agent_records_trusted_prompt_selection(self) -> None:
        await self._run(NovelAgent, "novel")

    async def test_specialized_agent_uses_its_own_prompt_identity(self) -> None:
        await self._run(ChapterAgent, "chapter")


if __name__ == "__main__":
    unittest.main()
