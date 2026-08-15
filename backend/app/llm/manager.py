import asyncio
import time

from collections.abc import AsyncIterator
from .registry import ProviderRegistry
from .schemas import ChatRequest, ChatResponse, ProviderStatus

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

    async def provider_status(
        self,
        *,
        probe: bool = False,
        timeout_ms: int = 3000,
    ) -> list[ProviderStatus]:
        async def resolve(name: str) -> ProviderStatus:
            descriptor = self._registry.describe(name)
            configured = self._registry.configured(name)
            available: bool | None = None
            latency_ms: float | None = None
            health_error: str | None = None

            if probe:
                if not configured:
                    available = False
                    health_error = "not_configured"
                else:
                    started = time.perf_counter()
                    try:
                        available = await asyncio.wait_for(
                            self.health(name),
                            timeout=timeout_ms / 1000,
                        )
                        if not available:
                            health_error = "health_check_failed"
                    except TimeoutError:
                        available = False
                        health_error = "health_check_timed_out"
                    except Exception:
                        available = False
                        health_error = "health_check_failed"
                    latency_ms = (time.perf_counter() - started) * 1000

            return ProviderStatus(
                **descriptor.model_dump(),
                configured=configured,
                available=available,
                latency_ms=latency_ms,
                health_error=health_error,
            )

        return list(
            await asyncio.gather(
                *(resolve(name) for name in self.providers())
            )
        )
