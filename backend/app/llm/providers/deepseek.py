import time
import uuid

from openai import AsyncOpenAI

from app.config.settings import get_settings

from app.llm.base import BaseChatProvider
from app.llm.schemas import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
)


class DeepSeekProvider(BaseChatProvider):

    name = "deepseek"


    def __init__(self):

        settings = get_settings()

        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )


    async def chat(
        self,
        request: ChatRequest
    ) -> ChatResponse:


        start = time.time()


        response = await self.client.chat.completions.create(
            model=request.model or "deepseek-chat",

            messages=[
                {
                    "role": msg.role,
                    "content": msg.content,
                }
                for msg in request.messages
            ],

            temperature=request.temperature
            or 0.7,

            max_tokens=request.max_tokens,
        )


        latency = (
            time.time() - start
        ) * 1000


        usage = None

        if response.usage:

            usage = TokenUsage(
                prompt_tokens=
                response.usage.prompt_tokens,

                completion_tokens=
                response.usage.completion_tokens,

                total_tokens=
                response.usage.total_tokens,
            )


        return ChatResponse(

            id=str(uuid.uuid4()),

            content=
            response.choices[0].message.content,

            model=response.model,

            provider=self.name,

            finish_reason=
            response.choices[0].finish_reason,

            usage=usage,

            latency_ms=latency,
        )


    async def stream_chat(
        self,
        request: ChatRequest
    ):

        stream = await self.client.chat.completions.create(

            model=request.model or "deepseek-chat",

            messages=[
                {
                    "role": msg.role,
                    "content": msg.content,
                }
                for msg in request.messages
            ],

            stream=True,

        )


        async for chunk in stream:

            if chunk.choices[0].delta.content:

                yield (
                    chunk
                    .choices[0]
                    .delta
                    .content
                )


    async def health(self):

        return bool(
            get_settings()
            .DEEPSEEK_API_KEY
        )