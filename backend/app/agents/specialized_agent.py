from __future__ import annotations

from abc import abstractmethod
from time import perf_counter

from app.agents.grounding import (
    GroundingMemory,
    agent_grounding_service,
)
from app.agents.novel_agent import NovelAgent
from app.agents.schemas import (
    AgentContext,
    AgentResult,
)


class SpecializedAgent(NovelAgent):

    _CREATIVE_MARKERS = (
        "\u521b\u4f5c",
        "\u751f\u6210",
        "\u8bbe\u8ba1",
        "\u6784\u601d",
        "\u7eed\u5199",
        "\u6539\u5199",
        "\u6269\u5199",
        "\u89c4\u5212",
        "\u63d0\u51fa\u5efa\u8bae",
        "\u63d0\u4f9b\u5efa\u8bae",
        "\u7ed9\u51fa\u5efa\u8bae",
        "\u65b0\u5267\u60c5",
        "\u65b0\u4eba\u7269",
        "\u65b0\u8bbe\u5b9a",
        "\u5927\u7eb2",
        "\u65b9\u6848",
    )

    _SINGLE_FACT_MARKERS = (
        "\u662f\u4ec0\u4e48",
        "\u662f\u8c01",
        "\u5728\u54ea\u91cc",
        "\u4f4d\u4e8e\u54ea\u91cc",
        "\u6765\u81ea\u54ea\u91cc",
        "\u64c5\u957f\u4ec0\u4e48",
        "\u4ec0\u4e48\u6027\u683c",
        "\u6709\u4f55\u7279\u70b9",
    )

    _LIST_MARKERS = (
        "\u6574\u7406",
        "\u6c47\u603b",
        "\u5217\u51fa",
        "\u6709\u54ea\u4e9b",
        "\u5168\u90e8",
        "\u5f53\u524d\u8bbe\u5b9a",
        "\u5df2\u7ecf\u786e\u8ba4",
        "\u5df2\u786e\u8ba4",
    )

    _CONFLICT_MARKERS = (
        "\u51b2\u7a81",
        "\u77db\u76fe",
        "\u4e00\u81f4\u6027",
        "\u6f0f\u6d1e",
        "\u65f6\u95f4\u7ebf",
    )

    @property
    @abstractmethod
    def memory_types(
        self,
    ) -> frozenset[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def grounding_label(
        self,
    ) -> str:
        raise NotImplementedError

    def _resolve_task_mode(
        self,
        context: AgentContext,
    ) -> str:

        if context.task_mode in {
            "grounded",
            "creative",
        }:
            return context.task_mode

        if any(
            marker in context.instruction
            for marker
            in self._CREATIVE_MARKERS
        ):
            return "creative"

        return "grounded"

    def _is_list_request(
        self,
        instruction: str,
    ) -> bool:

        return any(
            marker in instruction
            for marker
            in self._LIST_MARKERS
        )

    def _is_conflict_request(
        self,
        instruction: str,
    ) -> bool:

        return any(
            marker in instruction
            for marker
            in self._CONFLICT_MARKERS
        )

    def _is_single_fact_request(
        self,
        instruction: str,
    ) -> bool:

        return (
            any(
                marker in instruction
                for marker
                in self._SINGLE_FACT_MARKERS
            )
            and not self._is_list_request(
                instruction
            )
        )

    def _requires_type_scan(
        self,
        instruction: str,
    ) -> bool:

        return (
            self._is_list_request(
                instruction
            )
            or self._is_conflict_request(
                instruction
            )
        )

    @staticmethod
    def _normalize_sentence(
        content: str,
    ) -> str:

        content = str(
            content or ""
        ).strip()

        if not content:
            return ""

        if content.endswith(
            (
                "\u3002",
                "\uff01",
                "\uff1f",
                ".",
                "!",
                "?",
            )
        ):
            return content

        return content + "\u3002"

    def _select_evidence(
        self,
        context: AgentContext,
        memories: list[GroundingMemory],
    ) -> list[GroundingMemory]:

        if (
            memories
            and self._is_single_fact_request(
                context.instruction
            )
        ):
            return memories[:1]

        return memories

    def _no_memory_response(
        self,
        context: AgentContext,
    ) -> str:

        if (
            self.name == "plot"
            and self._is_conflict_request(
                context.instruction
            )
        ):
            return (
                "\u5f53\u524d\u957f\u671f\u8bb0\u5fc6\u4e2d"
                "\u6682\u65e0\u8db3\u591f\u7684\u5267\u60c5\u4e8b\u4ef6\uff0c"
                "\u65e0\u6cd5\u5224\u65ad\u662f\u5426\u5b58\u5728"
                "\u660e\u786e\u51b2\u7a81\u3002"
            )

        return (
            "\u5f53\u524d\u957f\u671f\u8bb0\u5fc6\u4e2d"
            "\u6682\u65e0\u4e0e\u8be5"
            + self.grounding_label
            + "\u95ee\u9898\u76f4\u63a5\u76f8\u5173"
            "\u7684\u5df2\u786e\u8ba4\u4fe1\u606f\u3002"
        )

    def _format_grounded_response(
        self,
        context: AgentContext,
        memories: list[GroundingMemory],
    ) -> str:

        if not memories:
            return self._no_memory_response(
                context
            )

        if (
            self.name == "plot"
            and self._is_conflict_request(
                context.instruction
            )
        ):

            lines = "\n".join(
                "- "
                + self._normalize_sentence(
                    memory.content
                )
                for memory
                in memories
            )

            if len(memories) < 2:
                return (
                    "\u5f53\u524d\u957f\u671f\u8bb0\u5fc6\u4e2d"
                    "\u7684\u5267\u60c5\u8bc1\u636e\u4e0d\u8db3\uff0c"
                    "\u65e0\u6cd5\u5224\u65ad\u662f\u5426\u5b58\u5728"
                    "\u660e\u786e\u51b2\u7a81\u3002\n\n"
                    "\u5df2\u786e\u8ba4\u7684\u76f8\u5173\u8bb0\u5f55\uff1a\n"
                    + lines
                )

            return (
                "\u6839\u636e\u957f\u671f\u8bb0\u5fc6\uff0c"
                "\u5f53\u524d\u5df2\u786e\u8ba4\u7684"
                "\u5267\u60c5\u8bb0\u5f55\u5982\u4e0b\uff1a\n"
                + lines
                + "\n\n"
                "\u4ec5\u51ed\u8fd9\u4e9b\u8bb0\u5f55"
                "\u65e0\u6cd5\u81ea\u52a8\u786e\u8ba4"
                "\u662f\u5426\u5b58\u5728\u660e\u786e\u51b2\u7a81\u3002"
            )

        if self._is_single_fact_request(
            context.instruction
        ):

            return (
                "\u6839\u636e\u957f\u671f\u8bb0\u5fc6\uff0c"
                + self._normalize_sentence(
                    memories[0].content
                )
            )

        lines = "\n".join(
            "- "
            + self._normalize_sentence(
                memory.content
            )
            for memory
            in memories
        )

        return (
            "\u6839\u636e\u957f\u671f\u8bb0\u5fc6\uff0c"
            "\u5f53\u524d\u5df2\u786e\u8ba4\u7684"
            + self.grounding_label
            + "\u5982\u4e0b\uff1a\n"
            + lines
        )

    async def _load_memories(
        self,
        context: AgentContext,
    ) -> tuple[list[GroundingMemory], str]:

        if not context.use_memory:
            return [], "disabled"

        if self._requires_type_scan(
            context.instruction
        ):

            memories = (
                await agent_grounding_service
                .list_by_types(
                    user_id=context.user_id,
                    novel_id=context.novel_id,
                    allowed_memory_types=(
                        self.memory_types
                    ),
                    top_k=50,
                )
            )

            return memories, "sqlite_type_scan"

        memories = (
            await agent_grounding_service.retrieve(
                user_id=context.user_id,
                novel_id=context.novel_id,
                query=context.instruction,
                allowed_memory_types=(
                    self.memory_types
                ),
                top_k=8,
                min_similarity=0.35,
            )
        )

        return memories, "hybrid_semantic"

    async def _run_grounded(
        self,
        context: AgentContext,
    ) -> AgentResult:

        start = perf_counter()

        memories, strategy = (
            await self._load_memories(
                context
            )
        )

        memories = self._select_evidence(
            context,
            memories,
        )

        content = self._format_grounded_response(
            context,
            memories,
        )

        metadata = dict(
            context.metadata
        )

        metadata.update(
            {
                "user_id": context.user_id,
                "novel_id": context.novel_id,
                "task_mode": "grounded",
                "grounding_enforced": True,
                "llm_called": False,
                "retrieval_strategy": strategy,
                "memory_used": bool(memories),
                "memory_count": len(memories),
                "memory_ids": [
                    memory.id
                    for memory
                    in memories
                ],
                "memory_types": sorted(
                    {
                        memory.memory_type
                        for memory
                        in memories
                    }
                ),
                "memory_tiers": sorted(
                    {
                        memory.memory_tier
                        for memory in memories
                    }
                ),
                "evidence": [
                    {
                        "id": memory.id,
                        "memory_type": (
                            memory.memory_type
                        ),
                        "content": memory.content,
                        "memory_tier": (
                            memory.memory_tier
                        ),
                        "similarity": (
                            memory.similarity
                        ),
                        "hybrid_score": (
                            memory.hybrid_score
                        ),
                    }
                    for memory
                    in memories
                ],
                "requested_provider": (
                    context.provider
                ),
                "requested_model": (
                    context.model
                ),
            }
        )

        return AgentResult(
            agent=self.name,
            success=True,
            content=content,
            provider="internal",
            model="deterministic-grounding",
            finish_reason="grounded",
            usage=None,
            latency_ms=(
                perf_counter() - start
            ) * 1000,
            metadata=metadata,
        )

    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:

        if (
            self._resolve_task_mode(
                context
            )
            == "grounded"
        ):
            return await self._run_grounded(
                context
            )

        result = await super().run(
            context
        )

        result.metadata.update(
            {
                "task_mode": "creative",
                "grounding_enforced": False,
                "llm_called": True,
            }
        )

        return result
