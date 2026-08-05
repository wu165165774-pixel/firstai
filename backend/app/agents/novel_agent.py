from __future__ import annotations

from textwrap import dedent

from app.agents.base import BaseAgent
from app.agents.schemas import (
    AgentContext,
    AgentResult,
)
from app.llm.manager import LLMManager
from app.llm.schemas import (
    ChatMessage,
    ChatRequest,
)
from app.memory.context import (
    memory_context_builder,
)


class NovelAgent(BaseAgent):
    """
    NovelForge ???? Agent?

    ?????

    1. ???????
    2. ?????????
    3. ???? LLM ???
    4. ???? AgentResult?

    ?? CharacterAgent?WorldAgent ? PlotAgent
    ????????????
    """

    def __init__(
        self,
        llm_manager: LLMManager,
    ) -> None:

        self._llm_manager = llm_manager

    @property
    def name(self) -> str:

        return "novel"

    @property
    def description(self) -> str:

        return (
            "?????? Agent?"
            "????????? LLM ???"
        )

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            ?? NovelForge ??????? Agent?

            ????????????????????
            ??????????????????????

            ?????

            1. ??????????????
            2. ??????????????
            3. ??????????????????????
            4. ????????????????
            5. ????????????????????????
            6. ??????????????????
            7. ??????????????????????
            """
        ).strip()

    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:

        messages: list[
            ChatMessage
        ] = [
            ChatMessage(
                role="system",
                content=self._system_prompt(),
            )
        ]

        if context.use_memory:

            memory_context = (
                await memory_context_builder.build(
                    user_id=context.user_id,
                    novel_id=context.novel_id,
                    query=context.instruction,
                    top_k=4,
                )
            )

            if memory_context:

                messages.append(
                    ChatMessage(
                        role="system",
                        content=memory_context,
                        metadata={
                            "source": (
                                "long_term_memory"
                            )
                        },
                    )
                )

        messages.extend(
            context.messages
        )

        messages.append(
            ChatMessage(
                role="user",
                content=context.instruction,
            )
        )

        request_metadata = dict(
            context.metadata
        )

        request_metadata.update(
            {
                "user_id": context.user_id,
                "novel_id": context.novel_id,
                "agent": self.name,
            }
        )

        request = ChatRequest(
            provider=context.provider,
            model=context.model,
            messages=messages,
            temperature=context.temperature,
            max_tokens=context.max_tokens,
            stream=False,
            metadata=request_metadata,
        )

        response = await self._llm_manager.chat(
            context.provider,
            request,
        )

        response_metadata = dict(
            response.metadata
        )

        response_metadata.update(
            {
                "user_id": context.user_id,
                "novel_id": context.novel_id,
            }
        )

        return AgentResult(
            agent=self.name,
            success=True,
            content=response.content,
            provider=response.provider,
            model=response.model,
            finish_reason=(
                response.finish_reason
            ),
            usage=response.usage,
            latency_ms=response.latency_ms,
            metadata=response_metadata,
        )
