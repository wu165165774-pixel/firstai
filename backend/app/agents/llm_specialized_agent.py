from __future__ import annotations

from abc import (
    abstractmethod,
)

from app.agents.novel_agent import (
    NovelAgent,
)
from app.agents.schemas import (
    AgentContext,
    AgentResult,
)
from app.llm.schemas import (
    ReasoningEffort,
)


class LLMSpecializedAgent(NovelAgent):
    """
    Base class for specialized agents that
    always use an LLM to generate or analyze text.
    """

    @property
    @abstractmethod
    def execution_mode(
        self,
    ) -> str:

        raise NotImplementedError

    @property
    def recommended_reasoning_effort(
        self,
    ) -> ReasoningEffort:

        return "none"

    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:

        result = await super().run(
            context
        )

        result.metadata.update(
            {
                "execution_mode": (
                    self.execution_mode
                ),
                "requested_task_mode": (
                    context.task_mode
                ),
                "llm_called": True,
                "grounding_enforced": False,
                "recommended_reasoning_effort": (
                    self.recommended_reasoning_effort
                ),
                "requested_reasoning_effort": (
                    context.reasoning_effort
                ),
            }
        )

        return result
