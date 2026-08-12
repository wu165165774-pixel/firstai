from __future__ import annotations

from textwrap import dedent

from app.memory.schemas import MemoryTier
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.retrieval.schemas import DualRetrievalRequest, RetrievalPath
from app.retrieval.service import dual_path_retriever


class MemoryContextBlock(str):
    """String-compatible context carrying retrieval diagnostics."""

    def __new__(
        cls,
        value: str,
        *,
        mode: str,
        degraded: bool,
        lanes: list[dict],
    ):
        instance = super().__new__(cls, value)
        instance.retrieval_mode = mode
        instance.retrieval_degraded = degraded
        instance.retrieval_lanes = lanes
        return instance


class MemoryContextBuilder:
    """Build a tier-aware memory evidence block for an LLM request."""

    def __init__(
        self,
        storage: SQLiteMemoryStorage | None = None,
    ) -> None:

        self._storage = storage or SQLiteMemoryStorage()

    @staticmethod
    def _line(memory) -> str:

        content = str(
            getattr(memory, "content", "") or ""
        ).strip()
        if not content:
            return ""

        memory_type = str(
            getattr(
                memory,
                "memory_type",
                getattr(memory, "evidence_type", ""),
            )
            or ""
        ).strip()
        if hasattr(getattr(memory, "memory_type", None), "value"):
            memory_type = memory.memory_type.value

        return f"- [{memory_type or 'other'}] {content}"

    async def build(
        self,
        user_id: str,
        novel_id: str,
        query: str = "",
        top_k: int = 6,
        session_id: str | None = None,
    ) -> str:

        user_id = str(user_id or "").strip()
        novel_id = str(novel_id or "").strip()
        query = str(query or "").strip()
        session_id = str(session_id or "").strip() or None

        if not user_id or not novel_id or not query:
            return ""

        limit = min(max(int(top_k), 1), 4)
        session_memories = []

        if session_id:
            session_memories = await self._storage.query(
                user_id=user_id,
                novel_id=novel_id,
                memory_tier=MemoryTier.SESSION,
                session_id=session_id,
            )
            session_memories = session_memories[:limit]

        retrieval = await dual_path_retriever.retrieve(
            DualRetrievalRequest(
                user_id=user_id,
                novel_id=novel_id,
                query=query,
                top_k=limit * 2,
                char_budget=1800,
                min_vector_similarity=0.35,
            )
        )

        working_memories = []
        long_term_memories = []
        graph_memories = []
        for evidence in retrieval.evidence:
            vector_sources = [
                source
                for source in evidence.sources
                if source.path == RetrievalPath.VECTOR
            ]
            if vector_sources:
                tier = str(
                    vector_sources[0].metadata.get(
                        "memory_tier",
                        MemoryTier.LONG_TERM.value,
                    )
                )
                target = (
                    working_memories
                    if tier == MemoryTier.WORKING.value
                    else long_term_memories
                )
            else:
                target = graph_memories
            target.append(evidence)

        working_memories = working_memories[:limit]
        long_term_memories = long_term_memories[:limit]
        graph_memories = graph_memories[:limit]

        sections: list[str] = []

        for title, memories in (
            (
                "【Session Memory｜当前交互，随会话关闭或过期】",
                session_memories,
            ),
            (
                "【Working Memory｜当前卷/弧/章节任务】",
                working_memories,
            ),
            (
                "【Long-term Memory｜长期检索证据】",
                long_term_memories,
            ),
            (
                "【Temporal Graph｜指定时间有效的关系与事件证据】",
                graph_memories,
            ),
        ):
            lines = [
                line
                for line in (
                    self._line(memory)
                    for memory in memories
                )
                if line
            ]
            if lines:
                sections.append(title + "\n" + "\n".join(lines))

        if not sections:
            return MemoryContextBlock(
                "",
                mode=retrieval.mode,
                degraded=retrieval.degraded,
                lanes=[
                    lane.model_dump(mode="json")
                    for lane in retrieval.lanes
                ],
            )

        header = dedent(
            """
            你是一名严格遵守小说设定的长篇小说 AI。

            以下是分层 Memory 证据，不是 Canonical Fact，不能覆盖
            [CANON FACTS - MUST NOT VIOLATE] 或 Chapter Plan Grounding。

            使用规则：

            1. Canon/规划与 Memory 冲突时，必须服从 Canon/规划。
            2. Session 只表示当前交互临时状态，不得当作长期事实。
            3. Working 只表示当前创作窗口中的任务与未解决状态。
            4. Long-term 是可跨会话召回的证据，但仍不是 Canon。
            5. 事实类问题只能复述直接证据，不得自行推断或拼接新结论。
            6. 不同层级互相冲突时必须指出冲突，不得静默覆盖。
            7. 新创作可以使用这些证据，但不得把新内容描述为既有记忆。
            8. Temporal Graph 与 Vector 证据已经过确定性融合和去重；
               Graph 不可用时系统会降级为 Vector-only，不得虚构 Graph 事实。

            ================ 分层小说记忆 ================
            """
        ).strip()

        text = "\n\n".join(
            [header, *sections, "============================================"]
        )
        return MemoryContextBlock(
            text,
            mode=retrieval.mode,
            degraded=retrieval.degraded,
            lanes=[
                lane.model_dump(mode="json")
                for lane in retrieval.lanes
            ],
        )


memory_context_builder = MemoryContextBuilder()
