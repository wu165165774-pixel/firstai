from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


NovelStatus = Literal[
    "planning",
    "writing",
    "paused",
    "completed",
    "archived",
]


class NovelProjectCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    genre: str = Field(default="", max_length=128)
    premise: str = Field(default="", max_length=8000)
    language: str = Field(default="zh-CN", min_length=1, max_length=32)
    target_word_count: int = Field(default=0, ge=0, le=100_000_000)
    status: NovelStatus = "planning"
    style_guide: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NovelProjectUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    genre: str | None = Field(default=None, max_length=128)
    premise: str | None = Field(default=None, max_length=8000)
    language: str | None = Field(default=None, min_length=1, max_length=32)
    target_word_count: int | None = Field(default=None, ge=0, le=100_000_000)
    status: NovelStatus | None = None
    style_guide: dict[str, Any] | None = None
    constraints: list[str] | None = None
    metadata: dict[str, Any] | None = None


class NovelProject(BaseModel):
    novel_id: str
    user_id: str
    title: str
    genre: str
    premise: str
    language: str
    target_word_count: int
    status: NovelStatus
    style_guide: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision: int
    story_bible_revision: int
    created_at: str
    updated_at: str


class StoryBibleUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    world: dict[str, Any] | None = None
    characters: list[dict[str, Any]] | None = None
    factions: list[dict[str, Any]] | None = None
    locations: list[dict[str, Any]] | None = None
    rules: list[dict[str, Any]] | None = None
    themes: list[str] | None = None
    timeline: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class StoryBible(BaseModel):
    novel_id: str
    revision: int
    world: dict[str, Any] = Field(default_factory=dict)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    factions: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str


class StoryBibleRevision(BaseModel):
    novel_id: str
    revision: int
    snapshot: StoryBible
    created_at: str


class NovelProjectResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: NovelProject


class NovelProjectListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[NovelProject] = Field(default_factory=list)


class StoryBibleResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: StoryBible


class StoryBibleRevisionResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: StoryBibleRevision


class StoryBibleRevisionListResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: list[StoryBibleRevision] = Field(default_factory=list)
