from abc import (
    ABC,
    abstractmethod,
)

from app.agents.schemas import (
    AgentContext,
    AgentResult,
)


class BaseAgent(ABC):
    """
    NovelForge Agent ???????
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Agent ?????
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Agent ?????
        """
        raise NotImplementedError

    @abstractmethod
    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:
        """
        ?? Agent ???
        """
        raise NotImplementedError
