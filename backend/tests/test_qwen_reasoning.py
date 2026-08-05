from __future__ import annotations

import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agents.novel_agent import (
    NovelAgent,
)
from app.agents.schemas import (
    AgentContext,
)
from app.llm.providers.qwen_local import (
    QwenLocalProvider,
)
from app.llm.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
)


class FakeAsyncStream:

    def __init__(
        self,
        chunks,
    ) -> None:

        self._chunks = iter(
            chunks
        )

    def __aiter__(
        self,
    ):

        return self

    async def __anext__(
        self,
    ):

        try:

            return next(
                self._chunks
            )

        except StopIteration:

            raise StopAsyncIteration


class QwenReasoningTests(
    unittest.IsolatedAsyncioTestCase
):

    @staticmethod
    def _response(
        content: str = "response",
    ):

        return SimpleNamespace(
            id="response-001",
            model="qwen3:8b",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=content
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    async def test_default_reasoning_is_none(
        self,
    ) -> None:

        provider = QwenLocalProvider()

        create = AsyncMock(
            return_value=self._response()
        )

        provider.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=create
                )
            )
        )

        request = ChatRequest(
            messages=[
                ChatMessage(
                    role="user",
                    content="hello",
                )
            ],
        )

        result = await provider.chat(
            request
        )

        kwargs = (
            create.await_args.kwargs
        )

        self.assertEqual(
            kwargs["extra_body"],
            {
                "reasoning_effort": "none",
            },
        )

        self.assertFalse(
            result.metadata[
                "thinking_enabled"
            ]
        )

    async def test_reasoning_and_zero_temperature_are_forwarded(
        self,
    ) -> None:

        provider = QwenLocalProvider()

        create = AsyncMock(
            return_value=self._response()
        )

        provider.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=create
                )
            )
        )

        request = ChatRequest(
            messages=[
                ChatMessage(
                    role="user",
                    content="analyze",
                )
            ],
            reasoning_effort="high",
            temperature=0.0,
            max_tokens=321,
        )

        result = await provider.chat(
            request
        )

        kwargs = (
            create.await_args.kwargs
        )

        self.assertEqual(
            kwargs["extra_body"],
            {
                "reasoning_effort": "high",
            },
        )

        self.assertEqual(
            kwargs["temperature"],
            0.0,
        )

        self.assertEqual(
            kwargs["max_tokens"],
            321,
        )

        self.assertTrue(
            result.metadata[
                "thinking_enabled"
            ]
        )

        self.assertEqual(
            result.metadata[
                "reasoning_effort"
            ],
            "high",
        )

    async def test_stream_forwards_reasoning_settings(
        self,
    ) -> None:

        provider = QwenLocalProvider()

        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="A"
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="B"
                        )
                    )
                ]
            ),
        ]

        create = AsyncMock(
            return_value=FakeAsyncStream(
                chunks
            )
        )

        provider.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=create
                )
            )
        )

        request = ChatRequest(
            messages=[
                ChatMessage(
                    role="user",
                    content="stream",
                )
            ],
            reasoning_effort="medium",
            temperature=0.2,
            max_tokens=222,
            stream=True,
        )

        output = []

        async for chunk in provider.stream_chat(
            request
        ):

            output.append(chunk)

        kwargs = (
            create.await_args.kwargs
        )

        self.assertEqual(
            "".join(output),
            "AB",
        )

        self.assertTrue(
            kwargs["stream"]
        )

        self.assertEqual(
            kwargs["extra_body"],
            {
                "reasoning_effort": "medium",
            },
        )

        self.assertEqual(
            kwargs["temperature"],
            0.2,
        )

        self.assertEqual(
            kwargs["max_tokens"],
            222,
        )

    async def test_novel_agent_forwards_reasoning_effort(
        self,
    ) -> None:

        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="answer",
                    model="qwen3:8b",
                    provider="qwen_local",
                )
            )
        )

        agent = NovelAgent(
            llm_manager
        )

        context = AgentContext(
            user_id="user001",
            novel_id="novel001",
            instruction="analyze plot",
            use_memory=False,
            reasoning_effort="medium",
        )

        await agent.run(
            context
        )

        called_request = (
            llm_manager
            .chat
            .await_args
            .args[1]
        )

        self.assertEqual(
            called_request.reasoning_effort,
            "medium",
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
