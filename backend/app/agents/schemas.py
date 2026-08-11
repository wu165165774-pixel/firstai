from __future__ import annotations

from typing import (
    Any,
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from app.llm.schemas import (
    ChatMessage,
    ReasoningEffort,
    TokenUsage,
)


AgentTaskMode = Literal[
    "auto",
    "grounded",
    "creative",
]


class AgentContext(BaseModel):
    """
    Agent 单次执行所需的上下文。
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    user_id: str = Field(
        min_length=1
    )

    novel_id: str = Field(
        min_length=1
    )

    instruction: str = Field(
        min_length=1
    )

    provider: str = "qwen_local"

    model: str | None = None

    messages: list[ChatMessage] = Field(
        default_factory=list
    )

    use_memory: bool = True

    use_canon: bool = True

    task_mode: AgentTaskMode = "auto"

    reasoning_effort: ReasoningEffort = "none"

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
    )

    max_tokens: int | None = Field(
        default=None,
        gt=0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class AgentResult(BaseModel):
    """
    Agent 执行结果。
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    agent: str

    success: bool = True

    content: str

    provider: str

    model: str

    finish_reason: str | None = None

    usage: TokenUsage | None = None

    latency_ms: float | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )
