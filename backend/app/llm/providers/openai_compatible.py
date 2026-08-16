from __future__ import annotations

import time
import uuid

from collections.abc import AsyncIterator
from typing import Any, Literal

from openai import AsyncOpenAI

from app.llm.base import BaseChatProvider
from app.llm.schemas import ChatMessage, ChatRequest, ChatResponse, TokenUsage


ReasoningMode = Literal["openai", "dashscope", "none"]


class OpenAICompatibleProvider(BaseChatProvider):
    """Shared adapter for OpenAI Chat Completions compatible APIs."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens_parameter: Literal[
            "max_tokens",
            "max_completion_tokens",
        ] = "max_tokens",
        reasoning_mode: ReasoningMode = "none",
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.max_tokens_parameter = max_tokens_parameter
        self.reasoning_mode = reasoning_mode
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    @staticmethod
    def _message_to_dict(message: ChatMessage) -> dict[str, str]:
        value = {
            "role": message.role,
            "content": message.content,
        }
        if message.name is not None:
            value["name"] = message.name
        if message.tool_call_id is not None:
            value["tool_call_id"] = message.tool_call_id
        return value

    def _build_completion_kwargs(
        self,
        request: ChatRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [
                self._message_to_dict(message)
                for message in request.messages
            ],
            "stream": stream,
        }

        if request.max_tokens is not None:
            kwargs[self.max_tokens_parameter] = request.max_tokens

        if self.reasoning_mode == "openai":
            if request.reasoning_effort != "none":
                kwargs["reasoning_effort"] = request.reasoning_effort
            elif request.temperature is not None:
                kwargs["temperature"] = request.temperature
        elif request.temperature is not None:
            kwargs["temperature"] = request.temperature

        if self.reasoning_mode == "dashscope":
            kwargs["extra_body"] = {
                "enable_thinking": request.reasoning_effort != "none",
            }

        return kwargs

    async def chat(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        response = await self.client.chat.completions.create(
            **self._build_completion_kwargs(request, stream=False)
        )
        latency_ms = (time.perf_counter() - started) * 1000

        raw_usage = getattr(response, "usage", None)
        usage = None
        if raw_usage is not None:
            prompt_tokens = int(
                getattr(raw_usage, "prompt_tokens", 0) or 0
            )
            completion_tokens = int(
                getattr(raw_usage, "completion_tokens", 0) or 0
            )
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=int(
                    getattr(raw_usage, "total_tokens", 0)
                    or prompt_tokens + completion_tokens
                ),
            )

        choice = response.choices[0]
        return ChatResponse(
            id=getattr(response, "id", None) or str(uuid.uuid4()),
            content=choice.message.content or "",
            model=(
                getattr(response, "model", None)
                or request.model
                or self.model
            ),
            provider=self.name,
            finish_reason=choice.finish_reason,
            usage=usage,
            latency_ms=latency_ms,
            metadata={
                "reasoning_effort": request.reasoning_effort,
                "thinking_enabled": request.reasoning_effort != "none",
            },
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            **self._build_completion_kwargs(request, stream=True)
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield content

    async def health(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False
