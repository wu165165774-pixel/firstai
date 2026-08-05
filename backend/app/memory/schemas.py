from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class MemoryType(str, Enum):

    SHORT_TERM="short_term"

    CHARACTER="character"

    PLOT="plot"

    WORLD="world"


class MemoryItem(BaseModel):

    id: str | None = None

    user_id: str

    novel_id: str

    memory_type: MemoryType

    content: str

    importance: float = Field(
        default=0.5,
        ge=0,
        le=1
    )

    hit_count: int = 1

    # 新增
    score: float = 0.0

    created_at: datetime | None = None

    updated_at: datetime | None = None

    last_accessed_at: datetime | None = None

    metadata: dict = {}