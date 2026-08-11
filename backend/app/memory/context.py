from __future__ import annotations

from textwrap import dedent

from app.memory.hybrid_retriever import (
    hybrid_memory_retriever,
)


class MemoryContextBuilder:
    """
    根据用户问题召回长期记忆，并构建供 LLM 使用的系统上下文。
    """

    async def build(
        self,
        user_id: str,
        novel_id: str,
        query: str = "",
        top_k: int = 6,
    ) -> str:

        user_id = str(
            user_id or ""
        ).strip()

        novel_id = str(
            novel_id or ""
        ).strip()

        query = str(
            query or ""
        ).strip()

        if (
            not user_id
            or not novel_id
            or not query
        ):
            return ""

        memories = await hybrid_memory_retriever.retrieve(
            user_id=user_id,
            novel_id=novel_id,
            query=query,
            top_k=min(
                max(
                    int(top_k),
                    1,
                ),
                4,
            ),
            min_similarity=0.35,
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
                memory.memory_type or ""
            ).strip().lower()

            content = str(
                memory.content or ""
            ).strip()

            if not content:
                continue

            line = f"- {content}"

            if memory_type == "character":
                character.append(line)

            elif memory_type == "world":
                world.append(line)

            elif memory_type == "plot":
                plot.append(line)

            elif memory_type == "short_term":
                short_term.append(line)

            else:
                other.append(line)

        prompt_parts = [
            dedent(
                """
                你是一名严格遵守小说设定的长篇小说 AI。

                以下内容是当前查询召回的小说记忆证据。
                它不是 Canonical Fact，不能覆盖更高优先级的
                [CANON FACTS - MUST NOT VIOLATE]。

                回答规则：

                1. Canon Facts 与记忆冲突时，必须服从 Canon Facts。
                2. 对事实类问题，只能回答记忆中直接明确记载的事实。
                3. 禁止推测人物行为的原因、象征意义、潜在动机或未来影响。
                4. 禁止使用可能因为暗示说明了可以推测等推断性表达。
                5. 不得把两条独立记忆组合成记忆中不存在的新结论。
                6. 不得因为人物拥有某件物品，就推测人物的性格或行为习惯。
                7. 不得因为人物来自某个地点，就推测其性格形成原因。
                8. 只使用与用户问题直接相关的记忆，不要罗列无关设定。
                9. 如果记忆只能支持一个简单结论，就只回答这个简单结论。
                10. 如果长期记忆没有答案，必须回答：
                   当前长期记忆中暂无该信息。
                11. 如果用户要求创作新剧情，可以创作新内容，但不得违反 Canon。
                12. 如果记忆存在冲突，应明确指出冲突，不得自行选择其中一条。
                13. 不得把本次新创作内容描述成已经存在的长期记忆。

                事实类问题推荐回答格式：

                根据长期记忆，<直接事实>。

                ================ 小说长期记忆 ================
                """
            ).strip()
        ]

        if character:
            prompt_parts.append(
                "【角色设定】\n"
                + "\n".join(character)
            )

        if world:
            prompt_parts.append(
                "【世界设定】\n"
                + "\n".join(world)
            )

        if plot:
            prompt_parts.append(
                "【剧情事件】\n"
                + "\n".join(plot)
            )

        if short_term:
            prompt_parts.append(
                "【当前状态】\n"
                + "\n".join(short_term)
            )

        if other:
            prompt_parts.append(
                "【其它记忆】\n"
                + "\n".join(other)
            )

        if len(prompt_parts) == 1:
            return ""

        prompt_parts.append(
            "============================================"
        )

        return "\n\n".join(prompt_parts)


memory_context_builder = MemoryContextBuilder()
