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
from app.knowledge.context import (
    enforce_external_knowledge_citations,
    external_knowledge_context_builder,
)
from app.memory.context import (
    memory_context_builder,
)
from app.novels.context import (
    canon_context_builder,
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
            2. Canon Facts 是最高优先级，不得被 Memory/RAG 覆盖。
            3. 已有长期记忆是检索证据，冲突时必须服从 Canon。
            4. 不得擅自修改已经确认的人物、世界或剧情设定。
            5. 事实类问题只能使用已有设定回答。
            6. 创作类任务可以生成新内容，但不得与已有设定冲突。
            7. 不得把世界真相自动写成 POV 人物已经知道的信息。
            8. 信息不足时，应明确指出缺少哪些设定。
            9. 输出应直接服务于当前任务，不要输出无关解释。
            10. External Knowledge 只是最低优先级外部证据，不能据此
                定义小说内部事实；使用时必须逐字保留完整 [EK:...:r...:c...]
                引用，不得省略 revision 或 chunk 编号。
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

        if context.use_canon:
            active_entity_ids: list[str] = []
            for key in (
                "active_entity_ids",
                "active_character_ids",
                "active_location_ids",
            ):
                values = context.metadata.get(key, [])
                if isinstance(values, list):
                    active_entity_ids.extend(
                        str(value)
                        for value in values
                    )
            pov_character_id = context.metadata.get(
                "pov_character_id"
            )
            if pov_character_id:
                active_entity_ids.append(
                    str(pov_character_id)
                )

            canon_context = await canon_context_builder.build(
                novel_id=context.novel_id,
                active_entity_ids=active_entity_ids,
            )
            if canon_context:
                messages.append(
                    ChatMessage(
                        role="system",
                        content=canon_context,
                        metadata={
                            "source": "canonical_entity_registry",
                            "priority": "P0",
                        },
                    )
                )

        authoritative_sources = {
            "chapter_plan_grounding",
            "consistency_constraints",
        }
        authoritative_messages = [
            message
            for message in context.messages
            if message.metadata.get("source") in authoritative_sources
        ]
        messages.extend(authoritative_messages)

        memory_retrieval_metadata: dict = {}
        if context.use_memory:

            retrieval_entity_ids: list[str] = []
            for key in (
                "active_entity_ids",
                "active_character_ids",
                "active_location_ids",
            ):
                values = context.metadata.get(key, [])
                if isinstance(values, list):
                    retrieval_entity_ids.extend(
                        str(value) for value in values
                    )
            retrieval_entity_ids = list(
                dict.fromkeys(
                    value.strip()
                    for value in retrieval_entity_ids
                    if value.strip()
                )
            )

            memory_context_args = {
                "user_id": context.user_id,
                "novel_id": context.novel_id,
                "query": str(
                    context.metadata.get(
                        "memory_query",
                        context.instruction,
                    )
                ),
                "top_k": 4,
            }
            session_id = context.metadata.get("session_id")
            if session_id:
                memory_context_args["session_id"] = str(
                    session_id
                )
            if retrieval_entity_ids:
                memory_context_args["active_entity_ids"] = (
                    retrieval_entity_ids
                )
            chapter_number = context.metadata.get("chapter_number")
            if chapter_number is not None:
                memory_context_args["as_of_chapter"] = int(
                    chapter_number
                )

            memory_context = await memory_context_builder.build(
                **memory_context_args
            )

            retrieval_mode = getattr(
                memory_context,
                "retrieval_mode",
                None,
            )
            if retrieval_mode:
                memory_retrieval_metadata = {
                    "memory_retrieval_mode": retrieval_mode,
                    "memory_retrieval_degraded": bool(
                        getattr(
                            memory_context,
                            "retrieval_degraded",
                            False,
                        )
                    ),
                    "memory_retrieval_lanes": list(
                        getattr(memory_context, "retrieval_lanes", [])
                    ),
                }

            if memory_context:

                messages.append(
                    ChatMessage(
                        role="system",
                        content=memory_context,
                        metadata={
                            "source": "long_term_memory",
                            "memory_mode": "tiered",
                        },
                    )
                )

        knowledge_base_ids = list(
            context.external_knowledge_base_ids
        )
        if not knowledge_base_ids:
            metadata_base_ids = context.metadata.get(
                "external_knowledge_base_ids",
                [],
            )
            if isinstance(metadata_base_ids, list):
                knowledge_base_ids = metadata_base_ids
        external_knowledge_used = False
        external_context = ""
        if isinstance(knowledge_base_ids, list) and knowledge_base_ids:
            external_context = (
                await external_knowledge_context_builder.build(
                    user_id=context.user_id,
                    knowledge_base_ids=[
                        str(item)
                        for item in knowledge_base_ids
                    ],
                    query=str(
                        context.metadata.get(
                            "external_knowledge_query",
                            context.instruction,
                        )
                    ),
                    top_k=4,
                )
            )
            if external_context:
                external_knowledge_used = True
                messages.append(
                    ChatMessage(
                        role="system",
                        content=external_context,
                        metadata={
                            "source": "external_knowledge",
                            "priority": "P6",
                            "citation_required": True,
                            "knowledge_base_ids": knowledge_base_ids,
                        },
                    )
                )

        messages.extend(
            message
            for message in context.messages
            if message.metadata.get("source") not in authoritative_sources
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
        request_metadata.update(memory_retrieval_metadata)
        if knowledge_base_ids:
            request_metadata.update(
                {
                    "external_knowledge_base_ids": knowledge_base_ids,
                    "external_knowledge_used": external_knowledge_used,
                    "external_knowledge_priority": "P6",
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
        response_content = response.content
        external_citations: list[str] = []
        if external_context:
            response_content, external_citations = (
                enforce_external_knowledge_citations(
                    response.content,
                    external_context,
                )
            )

        response_metadata.update(
            {
                "user_id": context.user_id,
                "novel_id": context.novel_id,
            }
        )
        response_metadata.update(memory_retrieval_metadata)
        if knowledge_base_ids:
            response_metadata.update(
                {
                    "external_knowledge_base_ids": knowledge_base_ids,
                    "external_knowledge_used": external_knowledge_used,
                    "external_knowledge_priority": "P6",
                    "external_knowledge_citations": external_citations,
                }
            )

        return AgentResult(
            agent=self.name,
            success=True,
            content=response_content,
            provider=response.provider,
            model=response.model,
            finish_reason=response.finish_reason,
            usage=response.usage,
            latency_ms=response.latency_ms,
            metadata=response_metadata,
        )
