from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemoryType(str, Enum):

    SHORT_TERM = "short_term"

    CHARACTER = "character"

    PLOT = "plot"

    WORLD = "world"


class MemoryTier(str, Enum):

    SESSION = "session"

    WORKING = "working"

    LONG_TERM = "long_term"


class MemoryItem(BaseModel):

    model_config = ConfigDict(extra="forbid")

    id: str | None = None

    user_id: str

    novel_id: str

    memory_type: MemoryType

    memory_tier: MemoryTier = MemoryTier.LONG_TERM

    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    content: str

    importance: float = Field(
        default=0.5,
        ge=0,
        le=1
    )

    hit_count: int = 1

    revision: int = Field(default=1, ge=1)

    # 新增
    score: float = 0.0

    created_at: datetime | None = None

    updated_at: datetime | None = None

    last_accessed_at: datetime | None = None

    expires_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_session_scope(self) -> "MemoryItem":

        if (
            self.memory_tier == MemoryTier.SESSION
            and not self.session_id
        ):
            raise ValueError(
                "session_id is required for session memory."
            )

        if (
            self.memory_tier != MemoryTier.SESSION
            and self.session_id is not None
        ):
            raise ValueError(
                "session_id is only valid for session memory."
            )

        return self


MemoryPromotionBasis = Literal[
    "frequency",
    "user_confirmed",
    "accepted_manuscript",
    "story_bible",
]


class MemoryPromotionRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)

    target_tier: Literal["working", "long_term"]

    basis: MemoryPromotionBasis

    reason: str = Field(min_length=1, max_length=1000)


class MemoryLifecycleSweepRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=128)

    novel_id: str = Field(min_length=1, max_length=128)

    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    dry_run: bool = False

    now: datetime | None = None


class MemorySessionCloseRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=128)

    novel_id: str = Field(min_length=1, max_length=128)


class MemoryLifecycleEvent(BaseModel):

    model_config = ConfigDict(extra="forbid")

    event_id: str

    memory_id: str

    user_id: str

    novel_id: str

    event_type: str

    from_tier: MemoryTier | None = None

    to_tier: MemoryTier | None = None

    reason: str

    payload: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime


class MemoryPromotionResult(BaseModel):

    model_config = ConfigDict(extra="forbid")

    memory: MemoryItem

    event: MemoryLifecycleEvent


class MemoryLifecycleSweepResult(BaseModel):

    model_config = ConfigDict(extra="forbid")

    dry_run: bool

    evicted_count: int = Field(ge=0)

    evicted_memory_ids: list[str] = Field(default_factory=list)
