from collections.abc import AsyncIterator
from .registry import ProviderRegistry
from .schemas import ChatRequest, ChatResponse

class LLMManager:
    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    async def chat(self, provider: str, request: ChatRequest) -> ChatResponse:
        return await self._registry.get(provider).chat(request)

    async def stream_chat(self, provider: str, request: ChatRequest) -> AsyncIterator[str]:
        async for chunk in self._registry.get(provider).stream_chat(request):
            yield chunk

    async def health(self, provider: str) -> bool:
        return await self._registry.get(provider).health()

    def providers(self) -> list[str]:
        return self._registry.list()
