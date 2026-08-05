from __future__ import annotations

from app.agents.character_agent import (
    CharacterAgent,
)
from app.agents.chapter_agent import (
    ChapterAgent,
)
from app.agents.manager import (
    AgentManager,
)
from app.agents.novel_agent import (
    NovelAgent,
)
from app.agents.plot_agent import (
    PlotAgent,
)
from app.agents.registry import (
    AgentRegistry,
)
from app.agents.review_agent import (
    ReviewAgent,
)
from app.agents.rewrite_agent import (
    RewriteAgent,
)
from app.agents.world_agent import (
    WorldAgent,
)
from app.llm.bootstrap import (
    llm_manager,
)


def create_agent_registry(
    llm_manager_instance,
) -> AgentRegistry:
    """
    Create and populate the NovelForge
    agent registry.
    """

    registry = AgentRegistry()

    agent_classes = (
        CharacterAgent,
        ChapterAgent,
        NovelAgent,
        PlotAgent,
        ReviewAgent,
        RewriteAgent,
        WorldAgent,
    )

    for agent_class in agent_classes:

        registry.register(
            agent_class(
                llm_manager_instance
            )
        )

    return registry


def create_agent_manager(
    llm_manager_instance,
) -> AgentManager:
    """
    创建 NovelForge AgentManager。

    使用一个新的、已经完成全部 Agent 注册的
    AgentRegistry 构建 AgentManager。
    """

    registry = create_agent_registry(
        llm_manager_instance
    )

    return AgentManager(
        registry
    )


agent_registry = create_agent_registry(
    llm_manager
)

agent_manager = AgentManager(
    agent_registry
)
