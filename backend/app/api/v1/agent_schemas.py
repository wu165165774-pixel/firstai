from pydantic import (
    BaseModel,
    Field,
)

from app.agents.schemas import AgentResult


class AgentInfo(BaseModel):

    name: str

    description: str


class AgentListData(BaseModel):

    agents: list[AgentInfo] = Field(
        default_factory=list
    )


class AgentListResponse(BaseModel):

    code: int = 0

    message: str = "success"

    data: AgentListData


class AgentExecuteResponse(BaseModel):

    code: int = 0

    message: str = "success"

    data: AgentResult
