from textwrap import dedent

from app.agents.specialized_agent import (
    SpecializedAgent,
)


class WorldAgent(SpecializedAgent):
    """
    世界观设定与世界规则一致性 Agent。
    """

    @property
    def name(self) -> str:

        return "world"

    @property
    def description(self) -> str:

        return (
            "负责世界观、地点、势力、历史、制度、"
            "力量体系以及世界规则一致性。"
        )

    @property
    def memory_types(
        self,
    ) -> frozenset[str]:

        return frozenset(
            {
                "world",
            }
        )

    @property
    def grounding_label(
        self,
    ) -> str:

        return "世界观设定"

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            你是 NovelForge 的世界观设定 Agent。

            你的职责包括：

            1. 创建和完善世界观设定。
            2. 设计地点、势力、历史、制度和文化。
            3. 维护力量体系、技术体系或魔法体系规则。
            4. 检查世界规则在不同剧情中的一致性。
            5. 分析新设定对现有世界结构的影响。

            执行规则：

            1. 已有长期记忆中的世界设定具有最高优先级。
            2. 不得擅自修改已经确认的世界规则。
            3. 不得为了推动剧情临时创造违反世界规则的能力。
            4. 事实类问题只能使用已有设定回答。
            5. 新增世界设定时，应明确标记为创作建议。
            6. 新设定应说明与已有地点、势力和历史的关系。
            7. 发现设定冲突时，应明确列出冲突内容。
            """
        ).strip()
