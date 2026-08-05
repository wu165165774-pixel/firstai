from __future__ import annotations

import time
import uuid

from collections.abc import (
    AsyncIterator,
)
from typing import Any

from openai import AsyncOpenAI

from app.llm.base import BaseChatProvider
from app.llm.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    TokenUsage,
)


class QwenLocalProvider(BaseChatProvider):
    """
    Local Qwen provider through Ollama's
    OpenAI-compatible API.
    """

    name = "qwen_local"

    def __init__(
        self,
        base_url: str = (
            "http://ollama:11434/v1"
        ),
        model: str = "qwen3:8b",
    ) -> None:

        self.model = model

        self.client = AsyncOpenAI(
            api_key="ollama",
            base_url=base_url,
        )

    @staticmethod
    def _message_to_dict(
        message: ChatMessage | dict[str, Any],
    ) -> dict[str, str]:

        if isinstance(
            message,
            ChatMessage,
        ):

            return {
                "role": message.role,
                "content": message.content,
            }

        return {
            "role": str(
                message["role"]
            ),
            "content": str(
                message["content"]
            ),
        }

    def _build_completion_kwargs(
        self,
        request: ChatRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:

        temperature = (
            0.7
            if request.temperature is None
            else request.temperature
        )

        kwargs: dict[str, Any] = {
            "model": (
                request.model
                or self.model
            ),
            "messages": [
                self._message_to_dict(
                    message
                )
                for message
                in request.messages
            ],
            "temperature": temperature,
            "stream": stream,
            "extra_body": {
                "reasoning_effort": (
                    request.reasoning_effort
                ),
            },
        }

        if request.max_tokens is not None:

            kwargs["max_tokens"] = (
                request.max_tokens
            )

        return kwargs

    async def chat(
        self,
        request: ChatRequest,
    ) -> ChatResponse:

        start = time.perf_counter()

        kwargs = (
            self._build_completion_kwargs(
                request,
                stream=False,
            )
        )

        response = (
            await self.client
            .chat
            .completions
            .create(
                **kwargs
            )
        )

        latency_ms = (
            time.perf_counter() - start
        ) * 1000

        usage = None

        if response.usage is not None:

            usage = TokenUsage(
                prompt_tokens=(
                    response.usage.prompt_tokens
                    or 0
                ),
                completion_tokens=(
                    response.usage
                    .completion_tokens
                    or 0
                ),
                total_tokens=(
                    response.usage.total_tokens
                    or 0
                ),
            )

        choice = response.choices[0]

        content = (
            choice.message.content
            or ""
        )

        selected_model = (
            getattr(
                response,
                "model",
                None,
            )
            or request.model
            or self.model
        )

        return ChatResponse(
            id=(
                getattr(
                    response,
                    "id",
                    None,
                )
                or str(uuid.uuid4())
            ),
            content=content,
            model=selected_model,
            provider=self.name,
            finish_reason=(
                choice.finish_reason
            ),
            usage=usage,
            latency_ms=latency_ms,
            metadata={
                "reasoning_effort": (
                    request.reasoning_effort
                ),
                "thinking_enabled": (
                    request.reasoning_effort
                    != "none"
                ),
            },
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[str]:

        kwargs = (
            self._build_completion_kwargs(
                request,
                stream=True,
            )
        )

        stream = (
            await self.client
            .chat
            .completions
            .create(
                **kwargs
            )
        )

        async for chunk in stream:

            if not chunk.choices:
                continue

            content = (
                chunk
                .choices[0]
                .delta
                .content
            )

            if content:
                yield content

    async def health(
        self,
    ) -> bool:

        try:

            await self.client.models.list()

            return True

        except Exception:

            return False
