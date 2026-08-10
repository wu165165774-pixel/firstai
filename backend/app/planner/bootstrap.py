from app.agents.manager import AgentManager
from app.agents.planner_agent import PlannerAgent
from app.agents.registry import AgentRegistry
from app.llm.bootstrap import registry as provider_registry
from app.llm.manager import LLMManager


planner_llm_manager = LLMManager(provider_registry)

planner_agent_registry = AgentRegistry()
planner_agent_registry.register(
    PlannerAgent(
        llm_manager=planner_llm_manager,
    )
)

planner_agent_manager = AgentManager(
    registry=planner_agent_registry,
)
