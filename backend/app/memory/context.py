from .manager import memory_manager


class MemoryContextBuilder:

    async def build(
        self,
        user_id: str,
        novel_id: str,
        query: str = ""
    ) -> str:

        memories = await memory_manager.retrieve_memory(
            user_id=user_id,
            novel_id=novel_id,
            query=query,
            top_k=5
        )

        if not memories:
            return ""

        character = []
        world = []
        plot = []
        other = []

        for memory in memories:

            memory_type = (
                memory.memory_type.value
                if hasattr(memory.memory_type, "value")
                else str(memory.memory_type)
            )

            line = f"- {memory.content}"

            if memory_type == "character":
                character.append(line)

            elif memory_type == "world":
                world.append(line)

            elif memory_type == "plot":
                plot.append(line)

            else:
                other.append(line)

        prompt = """
你是一名专业长篇小说AI。

回答用户时必须严格依据下面提供的长期记忆。

规则：

1、禁止编造任何人物、世界观、剧情。

2、如果长期记忆没有相关内容，请明确回答：

"当前长期记忆中暂无该信息。"

3、不要为了让回答更丰富而补充设定。

4、如果问题涉及多个方面，只回答长期记忆中存在的部分。

================ 小说长期记忆 ================

"""

        if character:
            prompt += "【角色】\n"
            prompt += "\n".join(character)
            prompt += "\n\n"

        if world:
            prompt += "【世界】\n"
            prompt += "\n".join(world)
            prompt += "\n\n"

        if plot:
            prompt += "【剧情】\n"
            prompt += "\n".join(plot)
            prompt += "\n\n"

        if other:
            prompt += "【其它】\n"
            prompt += "\n".join(other)
            prompt += "\n\n"

        prompt += "========================================"

        return prompt


memory_context_builder = MemoryContextBuilder()