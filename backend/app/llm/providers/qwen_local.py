import time
import uuid

from openai import AsyncOpenAI

from ..base import BaseChatProvider
from ..schemas import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
)


class QwenLocalProvider(BaseChatProvider):

    name = "qwen_local"


    def __init__(
        self,
        base_url: str = "http://ollama:11434/v1",
        model: str = "qwen3:8b",
    ):

        self.model = model

        self.client = AsyncOpenAI(

            api_key="ollama",

            base_url=base_url

        )


    async def chat(
        self,
        request: ChatRequest
    ) -> ChatResponse:


        start = time.time()

        print("\n========== SEND TO QWEN ==========")
        
        for msg in request.messages:
            print(msg)
        
        print("==================================\n")
        response = await self.client.chat.completions.create(

            model=request.model or self.model,

            extra_body={
                "reasoning_effort": "none",
            },
            messages=[
            
                {
                    "role": msg.role if hasattr(msg,"role") else msg["role"],
                    "content": msg.content if hasattr(msg,"content") else msg["content"],
                }
            
                for msg in request.messages
            
            ],


            temperature=request.temperature or 0.7,

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

            model=request.model or self.model,

            extra_body={
                "reasoning_effort": "none",
            },

            messages=[
            
                {
                    "role": msg.role if hasattr(msg,"role") else msg["role"],
                    "content": msg.content if hasattr(msg,"content") else msg["content"],
                }
            
                for msg in request.messages
            
            ],

            stream=True,

        )


        async for chunk in stream:

            if chunk.choices[0].delta.content:

                yield chunk.choices[0].delta.content



    async def health(self):

        try:

            models = await self.client.models.list()

            return True


        except Exception:

            return False
