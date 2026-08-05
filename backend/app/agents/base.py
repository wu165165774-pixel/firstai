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
    NovelForge Agent 抽象基类。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Agent 名称。
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Agent 描述。
        """
        raise NotImplementedError

    @abstractmethod
    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:
        """
        执行 Agent 任务。
        """
        raise NotImplementedError
