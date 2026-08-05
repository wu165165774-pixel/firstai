from app.agents.manager import AgentManager
from app.agents.novel_agent import NovelAgent
from app.agents.registry import AgentRegistry
from app.llm.manager import LLMManager


def create_agent_manager(
    llm_manager: LLMManager,
) -> AgentManager:
    """
    ?? NovelForge AgentManager?

    ????????????????????
    ?? Agent ?? LLM Bootstrap ???????
    """

    registry = AgentRegistry()

    registry.register(
        NovelAgent(
            llm_manager=llm_manager
        )
    )

    return AgentManager(
        registry=registry
    )
