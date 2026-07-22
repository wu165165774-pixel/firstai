import pytest
from app.llm.base import BaseChatProvider
from app.llm.exceptions import ProviderAlreadyRegisteredError, ProviderNotFoundError
from app.llm.manager import LLMManager
from app.llm.registry import ProviderRegistry
from app.llm.schemas import ChatMessage, ChatRequest, ChatResponse

class FakeProvider(BaseChatProvider):
    name = "fake"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=request.messages[-1].content,
            model="fake-model",
            provider=self.name,
        )

    async def stream_chat(self, request: ChatRequest):
        yield "hello"
        yield " world"

    async def health(self) -> bool:
        return True

def test_chat_message():
    message = ChatMessage(role="user", content="hello")
    assert message.role == "user"

@pytest.mark.asyncio
async def test_manager_chat():
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)
    response = await LLMManager(registry).chat(
        "fake",
        ChatRequest(messages=[ChatMessage(role="user", content="hello")]),
    )
    assert response.content == "hello"
    assert response.provider == "fake"

def test_missing_provider():
    with pytest.raises(ProviderNotFoundError):
        ProviderRegistry().get("missing")

def test_duplicate_provider():
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider)
    with pytest.raises(ProviderAlreadyRegisteredError):
        registry.register("fake", FakeProvider)
