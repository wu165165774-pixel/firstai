from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from .schemas import ChatRequest, ChatResponse

class BaseChatProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> bool:
        raise NotImplementedError
