from __future__ import annotations

from .schemas import (
    NovelPlan,
    NovelPlanRevision,
    NovelPlanUpdate,
    NovelProject,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryBible,
    StoryBibleRevision,
    StoryBibleUpdate,
)
from .storage import NovelProjectStorage


class NovelProjectService:

    def __init__(
        self,
        storage: NovelProjectStorage | None = None,
    ) -> None:
        self.storage = storage or NovelProjectStorage()

    def create_project(
        self,
        payload: NovelProjectCreate,
    ) -> NovelProject:
        return self.storage.create_project(payload)

    def get_project(
        self,
        novel_id: str,
    ) -> NovelProject:
        return self.storage.get_project(novel_id)

    def list_projects(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NovelProject]:
        return self.storage.list_projects(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def update_project(
        self,
        novel_id: str,
        payload: NovelProjectUpdate,
    ) -> NovelProject:
        return self.storage.update_project(
            novel_id,
            payload,
        )

    def get_story_bible(
        self,
        novel_id: str,
    ) -> StoryBible:
        return self.storage.get_story_bible(novel_id)

    def update_story_bible(
        self,
        novel_id: str,
        payload: StoryBibleUpdate,
    ) -> StoryBible:
        return self.storage.update_story_bible(
            novel_id,
            payload,
        )

    def list_story_bible_revisions(
        self,
        novel_id: str,
        *,
        limit: int = 100,
    ) -> list[StoryBibleRevision]:
        return self.storage.list_story_bible_revisions(
            novel_id,
            limit=limit,
        )

    def get_story_bible_revision(
        self,
        novel_id: str,
        revision: int,
    ) -> StoryBibleRevision:
        return self.storage.get_story_bible_revision(
            novel_id,
            revision,
        )
    def get_novel_plan(
        self,
        novel_id: str,
    ) -> NovelPlan:
        return self.storage.get_novel_plan(novel_id)

    def update_novel_plan(
        self,
        novel_id: str,
        payload: NovelPlanUpdate,
    ) -> NovelPlan:
        return self.storage.update_novel_plan(
            novel_id,
            payload,
        )

    def list_novel_plan_revisions(
        self,
        novel_id: str,
        *,
        limit: int = 100,
    ) -> list[NovelPlanRevision]:
        return self.storage.list_novel_plan_revisions(
            novel_id,
            limit=limit,
        )

    def get_novel_plan_revision(
        self,
        novel_id: str,
        revision: int,
    ) -> NovelPlanRevision:
        return self.storage.get_novel_plan_revision(
            novel_id,
            revision,
        )
