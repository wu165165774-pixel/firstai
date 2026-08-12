from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ExternalKnowledgeSourceType(str, Enum):
    WEB = "web"
    BOOK = "book"
    PAPER = "paper"
    DOCUMENT = "document"
    REFERENCE = "reference"
    OTHER = "other"


class ExternalKnowledgeSourceCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    source_type: ExternalKnowledgeSourceType
    title: str = Field(min_length=1, max_length=512)
    source_uri: str = Field(min_length=1, max_length=2048)
    content: str = Field(min_length=1, max_length=500_000)
    author: str | None = Field(default=None, max_length=512)
    published_at: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalKnowledgeSourceUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    content: str | None = Field(
        default=None,
        min_length=1,
        max_length=500_000,
    )
    author: str | None = Field(default=None, max_length=512)
    published_at: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ExternalKnowledgeSourceUpdate":
        changed = self.model_fields_set - {
            "user_id",
            "knowledge_base_id",
            "expected_revision",
        }
        if not changed:
            raise ValueError("External knowledge update has no changes.")
        return self


class ExternalKnowledgeScope(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)


class ExternalKnowledgeSource(BaseModel):
    source_id: str
    user_id: str
    knowledge_base_id: str
    source_type: ExternalKnowledgeSourceType
    source_uri: str
    current_revision: int
    title: str
    content: str
    content_hash: str
    author: str | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExternalKnowledgeSourceRevision(BaseModel):
    source_id: str
    revision: int
    title: str
    content: str
    content_hash: str
    author: str | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ExternalKnowledgeChunk(BaseModel):
    chunk_id: str
    source_id: str
    source_revision: int
    chunk_number: int
    content: str
    start_char: int
    end_char: int
    content_hash: str
    created_at: datetime


class ExternalKnowledgeCitation(BaseModel):
    citation_id: str
    source_id: str
    source_revision: int
    chunk_id: str
    chunk_number: int
    start_char: int
    end_char: int
    knowledge_base_id: str
    source_type: ExternalKnowledgeSourceType
    title: str
    source_uri: str
    author: str | None = None
    published_at: str | None = None


class ExternalKnowledgeHit(BaseModel):
    content: str
    similarity: float
    citation: ExternalKnowledgeCitation


class ExternalKnowledgeRetrieveRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)
    knowledge_base_ids: list[str] = Field(
        min_length=1,
        max_length=20,
    )
    query: str = Field(min_length=1, max_length=16_000)
    top_k: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.30, ge=-1.0, le=1.0)

    @field_validator("knowledge_base_ids")
    @classmethod
    def normalize_knowledge_base_ids(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            item = str(item or "").strip()
            if not item:
                raise ValueError("knowledge_base_ids must not contain blanks.")
            if len(item) > 128:
                raise ValueError("knowledge_base_id exceeds 128 characters.")
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized


class ExternalKnowledgeWriteResult(BaseModel):
    source: ExternalKnowledgeSource
    chunk_count: int
    indexed: bool


class ExternalKnowledgeDeleteResult(BaseModel):
    source_id: str
    deleted_revision_count: int
    deleted_chunk_count: int
    removed_vector_count: int


class ExternalKnowledgeIndexStatus(BaseModel):
    consistent: bool
    sqlite_count: int
    faiss_count_before: int
    faiss_count_after: int
    rebuilt: bool
    missing_in_faiss: list[str] = Field(default_factory=list)
    orphaned_in_faiss: list[str] = Field(default_factory=list)
    error: str | None = None
