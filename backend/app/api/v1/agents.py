from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.agents.bootstrap import (
    agent_manager,
)
from app.agents.errors import (
    AgentNotFoundError,
)
from app.agents.schemas import (
    AgentContext,
)
from app.api.v1.agent_schemas import (
    AgentExecuteResponse,
    AgentInfo,
    AgentListData,
    AgentListResponse,
)


router = APIRouter(
    prefix="/agents"
)


@router.get(
    "",
    response_model=AgentListResponse,
)
async def list_agents() -> AgentListResponse:
    """
    返回当前已经注册的 Agent。
    """

    agents: list[AgentInfo] = []

    registry = agent_manager.registry()

    for agent_name in agent_manager.agents():

        agent = registry.get(
            agent_name
        )

        agents.append(
            AgentInfo(
                name=agent.name,
                description=agent.description,
            )
        )

    return AgentListResponse(
        data=AgentListData(
            agents=agents
        )
    )


@router.post(
    "/{agent_name}/execute",
    response_model=AgentExecuteResponse,
)
async def execute_agent(
    agent_name: str,
    request: AgentContext,
) -> AgentExecuteResponse:
    """
    执行指定 Agent。
    """

    try:

        result = await agent_manager.execute(
            agent_name=agent_name,
            context=request,
        )

    except AgentNotFoundError as exc:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return AgentExecuteResponse(
        data=result
    )
