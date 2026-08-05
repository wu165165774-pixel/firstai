from __future__ import annotations

from typing import Any

from app.agents.registry import AgentRegistry
from app.agents.schemas import (
    AgentContext,
    AgentResult,
)


class AgentManager:
    """
    Agent ???????
    """

    def __init__(
        self,
        registry: AgentRegistry,
    ) -> None:

        self._registry = registry

    async def execute(
        self,
        agent_name: str,
        context: AgentContext | dict[str, Any],
    ) -> AgentResult:

        if not isinstance(
            context,
            AgentContext,
        ):

            context = AgentContext.model_validate(
                context
            )

        agent = self._registry.get(
            agent_name
        )

        return await agent.run(
            context
        )

    def agents(
        self,
    ) -> list[str]:

        return self._registry.list()

    def registry(
        self,
    ) -> AgentRegistry:

        return self._registry
