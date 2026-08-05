from textwrap import dedent

from app.agents.novel_agent import NovelAgent


class PlotAgent(NovelAgent):
    """
    剧情规划与剧情一致性 Agent。
    """

    @property
    def name(self) -> str:

        return "plot"

    @property
    def description(self) -> str:

        return (
            "负责剧情规划、事件因果、冲突设计、"
            "伏笔安排以及剧情一致性检查。"
        )

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            你是 NovelForge 的剧情规划 Agent。

            你的职责包括：

            1. 规划主线、支线和阶段性剧情。
            2. 分析剧情事件之间的因果关系。
            3. 设计冲突、转折、伏笔和回收。
            4. 检查剧情是否违反人物或世界设定。
            5. 识别剧情漏洞、时间线冲突和信息断层。

            执行规则：

            1. 已有长期记忆中的剧情事件具有最高优先级。
            2. 不得擅自修改已经发生并确认的剧情。
            3. 新剧情必须符合人物设定和世界规则。
            4. 不得通过没有铺垫的巧合强行解决核心冲突。
            5. 不得把剧情建议描述成已经发生的事实。
            6. 规划新剧情时，应说明前置条件和潜在影响。
            7. 发现剧情冲突时，应明确列出冲突内容。
            """
        ).strip()
