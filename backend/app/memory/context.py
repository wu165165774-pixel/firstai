from __future__ import annotations

from app.memory.hybrid_retriever import (
    hybrid_memory_retriever,
)


class MemoryContextBuilder:

    async def build(
        self,
        user_id: str,
        novel_id: str,
        query: str = "",
        top_k: int = 6,
    ) -> str:

        query = str(
            query
            or ""
        ).strip()

        if not query:
            return ""

        memories = (
            await hybrid_memory_retriever.retrieve(
                user_id=user_id,
                novel_id=novel_id,
                query=query,
                top_k=top_k,
                min_similarity=0.25,
            )
        )

        if not memories:
            return ""

        character: list[str] = []

        world: list[str] = []

        plot: list[str] = []

        short_term: list[str] = []

        other: list[str] = []

        for memory in memories:

            memory_type = str(
                memory.memory_type
            ).lower()

            line = f"- {memory.content}"

            if memory_type == "character":

                character.append(
                    line
                )

            elif memory_type == "world":

                world.append(
                    line
                )

            elif memory_type == "plot":

                plot.append(
                    line
                )

            elif memory_type == "short_term":

                short_term.append(
                    line
                )

            else:

                other.append(
                    line
                )

        prompt_parts = [
            """
你是一名专业长篇小说 AI。

回答用户时必须严格依据下面提供的小说长期记忆。

规则：

1. 只允许使用长期记忆中已经存在的设定。
2. 禁止编造人物身份、人物关系、世界观和历史事件。
3. 如果长期记忆没有相关内容，必须明确回答：
   “当前长期记忆中暂无该信息。”
4. 不要为了让回答更丰富而补充未经确认的设定。
5. 如果用户要求创作新剧情，应保证新剧情不违反已有记忆。
6. 如果记忆之间存在冲突，不要自行决定哪一条正确，应指出冲突。
7. 以下记忆已经按语义相关性和重要程度排序。

================ 小说长期记忆 ================
""".strip()
        ]

        if character:

            prompt_parts.append(
                "【角色设定】\n"
                + "\n".join(
                    character
                )
            )

        if world:

            prompt_parts.append(
                "【世界设定】\n"
                + "\n".join(
                    world
                )
            )

        if plot:

            prompt_parts.append(
                "【剧情事件】\n"
                + "\n".join(
                    plot
                )
            )

        if short_term:

            prompt_parts.append(
                "【当前状态】\n"
                + "\n".join(
                    short_term
                )
            )

        if other:

            prompt_parts.append(
                "【其它记忆】\n"
                + "\n".join(
                    other
                )
            )

        prompt_parts.append(
            "============================================"
        )

        return "\n\n".join(
            prompt_parts
        )


memory_context_builder = MemoryContextBuilder()