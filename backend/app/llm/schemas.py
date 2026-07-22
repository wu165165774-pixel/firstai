from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["system", "user", "assistant", "tool", "developer"]

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: ChatRole
    content: str = Field(min_length=1)
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

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
