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
    NovelForge 通用小说 Agent。

    当前职责：

    1. 接收小说任务；
    2. 按需召回长期记忆；
    3. 构造统一 LLM 请求；
    4. 返回标准 AgentResult。

    后续 CharacterAgent、WorldAgent 和 PlotAgent
    可以在该基础上继续扩展。
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
            "通用小说任务 Agent，"
            "支持长期记忆召回和 LLM 调用。"
        )

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            你是 NovelForge 的通用小说创作 Agent。

            你的任务是根据用户指令完成小说相关工作，
            包括设定分析、剧情讨论、文本创作和内容修改。

            执行规则：

            1. 严格遵守用户提供的任务要求。
            2. 已有长期记忆优先于一般推测。
            3. 不得擅自修改已经确认的人物、世界或剧情设定。
            4. 事实类问题只能使用已有设定回答。
            5. 创作类任务可以生成新内容，但不得与已有设定冲突。
            6. 信息不足时，应明确指出缺少哪些设定。
            7. 输出应直接服务于当前任务，不要输出无关解释。
            """
        ).strip()

    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:

        messages: list[ChatMessage] = [
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
                            "source": "long_term_memory"
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
            reasoning_effort=context.reasoning_effort,
            stream=False,
            metadata=request_metadata,
        )

        response = await self._llm_manager.chat(
            context.provider,
            request,
        )

        response_metadata = dict(
            response.metadata or {}
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
            finish_reason=response.finish_reason,
            usage=response.usage,
            latency_ms=response.latency_ms,
            metadata=response_metadata,
        )
