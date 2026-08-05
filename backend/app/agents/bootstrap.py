from app.agents.manager import AgentManager
from app.agents.novel_agent import NovelAgent
from app.agents.registry import AgentRegistry
from app.llm.bootstrap import llm_manager
from app.llm.manager import LLMManager


def create_agent_manager(
    llm_manager_instance: LLMManager,
) -> AgentManager:
    """
    创建 NovelForge AgentManager。

    使用依赖注入创建 Agent 注册表和执行管理器，
    便于测试以及后续扩展专业 Agent。
    """

    registry = AgentRegistry()

    registry.register(
        NovelAgent(
            llm_manager=llm_manager_instance
        )
    )

    return AgentManager(
        registry=registry
    )


agent_manager = create_agent_manager(
    llm_manager
)

agent_registry = agent_manager.registry()
