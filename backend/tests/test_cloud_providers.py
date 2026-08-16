import unittest

from types import SimpleNamespace

from app.config.settings import settings
from app.llm.exceptions import ProviderRequestError
from app.llm.providers.claude import ClaudeProvider
from app.llm.providers.dashscope import DashScopeProvider
from app.llm.providers.openai_cloud import OpenAIProvider
from app.llm.schemas import ChatMessage, ChatRequest


class AsyncSequence:
    def __init__(self, values):
        self._values = iter(values)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._values)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeModels:
    def __init__(self) -> None:
        self.calls = []

    async def list(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[])


class FakeOpenAICompletions:
    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["stream"]:
            return AsyncSequence(
                [
                    SimpleNamespace(choices=[]),
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="云"),
                            )
                        ]
                    ),
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="端"),
                            )
                        ]
                    ),
                ]
            )
        return SimpleNamespace(
            id="response-1",
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="云端响应"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
            ),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.completions = FakeOpenAICompletions()
        self.chat = SimpleNamespace(completions=self.completions)
        self.models = FakeModels()


class FakeClaudeMessages:
    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["stream"]:
            return AsyncSequence(
                [
                    SimpleNamespace(type="message_start"),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="text_delta",
                            text="克",
                        ),
                    ),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="text_delta",
                            text="劳德",
                        ),
                    ),
                ]
            )
        return SimpleNamespace(
            id="message-1",
            model=kwargs["model"],
            content=[
                SimpleNamespace(type="thinking", thinking="private"),
                SimpleNamespace(type="text", text="Claude 响应"),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=13, output_tokens=5),
        )


class FakeClaudeClient:
    def __init__(self) -> None:
        self.messages = FakeClaudeMessages()
        self.models = FakeModels()


class CloudProviderAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original = {
            "openai_api_key": settings.openai_api_key,
            "openai_base_url": settings.openai_base_url,
            "openai_model": settings.openai_model,
            "claude_api_key": settings.claude_api_key,
            "claude_base_url": settings.claude_base_url,
            "claude_model": settings.claude_model,
            "claude_max_tokens": settings.claude_max_tokens,
            "dashscope_api_key": settings.dashscope_api_key,
            "dashscope_base_url": settings.dashscope_base_url,
            "dashscope_model": settings.dashscope_model,
        }
        settings.openai_api_key = "test-openai-key"
        settings.openai_model = "openai-test"
        settings.claude_api_key = "test-claude-key"
        settings.claude_model = "claude-test"
        settings.claude_max_tokens = 2048
        settings.dashscope_api_key = "test-dashscope-key"
        settings.dashscope_model = "dashscope-test"

    def tearDown(self) -> None:
        for field, value in self.original.items():
            setattr(settings, field, value)

    async def test_openai_maps_reasoning_tokens_and_usage(self) -> None:
        client = FakeOpenAIClient()
        provider = OpenAIProvider(client=client)
        response = await provider.chat(
            ChatRequest(
                provider="openai",
                model="openai-override",
                messages=[
                    ChatMessage(role="user", content="hello", name="author"),
                    ChatMessage(
                        role="tool",
                        content="tool result",
                        tool_call_id="call-1",
                    ),
                ],
                reasoning_effort="medium",
                temperature=0.2,
                max_tokens=321,
            )
        )

        kwargs = client.completions.calls[0]
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["max_completion_tokens"], 321)
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(kwargs["messages"][0]["name"], "author")
        self.assertEqual(
            kwargs["messages"][1]["tool_call_id"],
            "call-1",
        )
        self.assertEqual(response.provider, "openai")
        self.assertEqual(response.model, "openai-override")
        self.assertEqual(response.content, "云端响应")
        self.assertEqual(response.usage.total_tokens, 18)

    async def test_openai_stream_and_health(self) -> None:
        client = FakeOpenAIClient()
        provider = OpenAIProvider(client=client)
        request = ChatRequest(
            provider="openai",
            messages=[ChatMessage(role="user", content="hello")],
            reasoning_effort="none",
            temperature=0.0,
        )

        chunks = [chunk async for chunk in provider.stream_chat(request)]
        self.assertEqual(chunks, ["云", "端"])
        self.assertEqual(client.completions.calls[0]["temperature"], 0.0)
        self.assertTrue(await provider.health())
        self.assertEqual(client.models.calls, [{}])

    async def test_dashscope_maps_thinking_and_streams_content(self) -> None:
        client = FakeOpenAIClient()
        provider = DashScopeProvider(client=client)
        request = ChatRequest(
            provider="dashscope",
            messages=[ChatMessage(role="user", content="hello")],
            reasoning_effort="high",
            temperature=0.1,
            max_tokens=456,
        )

        chunks = [chunk async for chunk in provider.stream_chat(request)]
        kwargs = client.completions.calls[0]
        self.assertEqual(chunks, ["云", "端"])
        self.assertEqual(kwargs["max_tokens"], 456)
        self.assertEqual(kwargs["temperature"], 0.1)
        self.assertEqual(kwargs["extra_body"], {"enable_thinking": True})

    async def test_claude_translates_system_and_maps_response(self) -> None:
        client = FakeClaudeClient()
        provider = ClaudeProvider(client=client)
        response = await provider.chat(
            ChatRequest(
                provider="claude",
                messages=[
                    ChatMessage(role="system", content="system one"),
                    ChatMessage(role="developer", content="system two"),
                    ChatMessage(role="user", content="first"),
                    ChatMessage(role="user", content="second"),
                ],
                reasoning_effort="medium",
                max_tokens=512,
            )
        )

        kwargs = client.messages.calls[0]
        self.assertEqual(kwargs["system"], "system one\n\nsystem two")
        self.assertEqual(
            kwargs["messages"],
            [{"role": "user", "content": "first\n\nsecond"}],
        )
        self.assertEqual(kwargs["max_tokens"], 512)
        self.assertEqual(response.content, "Claude 响应")
        self.assertEqual(response.finish_reason, "end_turn")
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertEqual(
            response.metadata["reasoning_effort_applied"],
            "none",
        )

    async def test_claude_stream_health_and_plain_tool_guard(self) -> None:
        client = FakeClaudeClient()
        provider = ClaudeProvider(client=client)
        request = ChatRequest(
            provider="claude",
            messages=[ChatMessage(role="user", content="hello")],
        )

        chunks = [chunk async for chunk in provider.stream_chat(request)]
        self.assertEqual(chunks, ["克", "劳德"])
        self.assertTrue(await provider.health())
        self.assertEqual(client.models.calls, [{"limit": 1}])

        with self.assertRaisesRegex(ProviderRequestError, "plain tool"):
            await provider.chat(
                ChatRequest(
                    provider="claude",
                    messages=[
                        ChatMessage(
                            role="tool",
                            content="unsupported",
                            tool_call_id="call-1",
                        )
                    ],
                )
            )


if __name__ == "__main__":
    unittest.main()
