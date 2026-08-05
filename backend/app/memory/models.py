from datetime import datetime
from pydantic import BaseModel, Field
from uuid import uuid4


class MemoryItem(BaseModel):

    id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    user_id: str

    novel_id: str

    memory_type: str

    content: str

    importance: float = 0.5

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    metadata: dict = {}