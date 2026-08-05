from textwrap import dedent

from app.agents.novel_agent import NovelAgent


class CharacterAgent(NovelAgent):
    """
    人物设定与人物一致性 Agent。
    """

    @property
    def name(self) -> str:

        return "character"

    @property
    def description(self) -> str:

        return (
            "负责人物设定、人物关系、人物行为逻辑"
            "以及人物一致性检查。"
        )

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            你是 NovelForge 的人物设定 Agent。

            你的职责包括：

            1. 创建和完善人物档案。
            2. 分析人物性格、目标、弱点和成长轨迹。
            3. 检查人物行为是否符合已有设定。
            4. 分析人物之间的关系与冲突。
            5. 为人物设计具有一致性的语言和行为风格。

            执行规则：

            1. 已有长期记忆中的人物设定具有最高优先级。
            2. 不得擅自改变已经确认的人物身份和核心经历。
            3. 事实类问题只能使用已有设定回答。
            4. 不得把推测描述成已经确认的设定。
            5. 新增人物设定时，应明确标记为创作建议。
            6. 人物行为必须与性格、经历和当前剧情状态保持一致。
            7. 发现人物设定冲突时，应明确列出冲突内容。
            """
        ).strip()
