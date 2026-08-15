from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["system", "user", "assistant", "tool", "developer"]

ReasoningEffort = Literal[
    "none",
    "low",
    "medium",
    "high",
]

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: ChatRole
    content: str = Field(min_length=1)
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class ChatRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")


    provider: str = "qwen_local"


    messages: list[ChatMessage] = Field(
        min_length=1
    )


    model: str | None = None


    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0
    )


    max_tokens: int | None = Field(
        default=None,
        gt=0
    )


    reasoning_effort: ReasoningEffort = "none"

    stream: bool = False


    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class ChatResponse(BaseModel):
    id: str | None = None
    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


ProviderKind = Literal["local", "cloud", "custom"]


class ProviderDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)
    kind: ProviderKind = "custom"
    default_model: str | None = Field(default=None, max_length=256)
    supported_models: list[str] = Field(default_factory=list, max_length=50)
    streaming: bool = True
    reasoning_efforts: list[ReasoningEffort] = Field(default_factory=list)
    requires_api_key: bool = False


class ProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ProviderKind
    registered: bool = True
    configured: bool
    available: bool | None = None
    default_model: str | None = None
    supported_models: list[str] = Field(default_factory=list)
    streaming: bool
    reasoning_efforts: list[ReasoningEffort] = Field(default_factory=list)
    requires_api_key: bool
    latency_ms: float | None = Field(default=None, ge=0)
    health_error: str | None = None


class ProviderCatalogData(BaseModel):
    providers: list[str] = Field(default_factory=list)
    catalog: list[ProviderStatus] = Field(default_factory=list)
    probed: bool = False


class ProviderCatalogResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: ProviderCatalogData
