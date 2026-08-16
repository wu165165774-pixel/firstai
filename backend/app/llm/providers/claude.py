from __future__ import annotations

import time
import uuid

from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from app.config.settings import get_settings
from app.llm.base import BaseChatProvider
from app.llm.exceptions import (
    ProviderConfigurationError,
    ProviderRequestError,
)
from app.llm.schemas import ChatRequest, ChatResponse, TokenUsage


class ClaudeProvider(BaseChatProvider):
    name = "claude"

    def __init__(self, *, client: Any | None = None) -> None:
        settings = get_settings()
        if not all(
            (
                settings.claude_api_key.strip(),
                settings.claude_base_url.strip(),
                settings.claude_model.strip(),
            )
        ):
            raise ProviderConfigurationError(
                "Claude provider is not configured."
            )
        self.model = settings.claude_model
        self.default_max_tokens = settings.claude_max_tokens
        self.client = client or AsyncAnthropic(
            api_key=settings.claude_api_key,
            base_url=settings.claude_base_url,
        )

    def _build_message_kwargs(
        self,
        request: ChatRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        system_parts: list[str] = []
        messages: list[dict[str, str]] = []

        for message in request.messages:
            if message.role in {"system", "developer"}:
                system_parts.append(message.content)
                continue
            if message.role == "tool":
                raise ProviderRequestError(
                    "Claude provider does not support plain tool messages."
                )

            role = message.role
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + message.content
            else:
                messages.append({"role": role, "content": message.content})

        if not messages:
            raise ProviderRequestError(
                "Claude provider requires a user or assistant message."
            )

        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "max_tokens": request.max_tokens or self.default_max_tokens,
            "stream": stream,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        return kwargs

    @staticmethod
    def _text_content(response: Any) -> str:
        return "".join(
            str(block.text)
            for block in response.content
            if getattr(block, "type", None) == "text"
            and getattr(block, "text", None)
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        response = await self.client.messages.create(
            **self._build_message_kwargs(request, stream=False)
        )
        latency_ms = (time.perf_counter() - started) * 1000

        raw_usage = getattr(response, "usage", None)
        usage = None
        if raw_usage is not None:
            prompt_tokens = int(
                getattr(raw_usage, "input_tokens", 0) or 0
            )
            completion_tokens = int(
                getattr(raw_usage, "output_tokens", 0) or 0
            )
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )

        return ChatResponse(
            id=getattr(response, "id", None) or str(uuid.uuid4()),
            content=self._text_content(response),
            model=(
                getattr(response, "model", None)
                or request.model
                or self.model
            ),
            provider=self.name,
            finish_reason=getattr(response, "stop_reason", None),
            usage=usage,
            latency_ms=latency_ms,
            metadata={
                "reasoning_effort_requested": request.reasoning_effort,
                "reasoning_effort_applied": "none",
                "thinking_enabled": False,
            },
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[str]:
        stream = await self.client.messages.create(
            **self._build_message_kwargs(request, stream=True)
        )
        async for event in stream:
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) != "text_delta":
                continue
            text = getattr(delta, "text", None)
            if text:
                yield text

    async def health(self) -> bool:
        try:
            await self.client.models.list(limit=1)
            return True
        except Exception:
            return False
