from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.errors import (
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
)


class AgentRegistry:
    """
    Agent ?????
    """

    def __init__(self) -> None:

        self._agents: dict[
            str,
            BaseAgent,
        ] = {}

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:

        normalized = str(
            name or ""
        ).strip().lower()

        if not normalized:

            raise ValueError(
                "Agent name must not be empty."
            )

        return normalized

    def register(
        self,
        agent: BaseAgent,
    ) -> BaseAgent:

        if not isinstance(
            agent,
            BaseAgent,
        ):

            raise TypeError(
                "agent must be an instance "
                "of BaseAgent."
            )

        name = self._normalize_name(
            agent.name
        )

        if name in self._agents:

            raise AgentAlreadyRegisteredError(
                f"Agent already registered: {name}"
            )

        self._agents[name] = agent

        return agent

    def get(
        self,
        name: str,
    ) -> BaseAgent:

        normalized = self._normalize_name(
            name
        )

        try:

            return self._agents[
                normalized
            ]

        except KeyError as exc:

            raise AgentNotFoundError(
                f"Agent not found: {normalized}"
            ) from exc

    def contains(
        self,
        name: str,
    ) -> bool:

        try:

            normalized = self._normalize_name(
                name
            )

        except ValueError:

            return False

        return normalized in self._agents

    def list(
        self,
    ) -> list[str]:

        return sorted(
            self._agents.keys()
        )
