from __future__ import annotations

from .schemas import (
    ChapterPlan,
    ChapterPlanCreate,
    ChapterPlanRevision,
    ChapterPlanUpdate,
    EntityResolution,
    EntityResolveRequest,
    NovelPlan,
    NovelPlanRevision,
    NovelPlanUpdate,
    NovelEntity,
    NovelEntityCreate,
    NovelEntityUpdate,
    NovelProject,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryArc,
    StoryArcCreate,
    StoryArcRevision,
    StoryArcUpdate,
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

    def create_entity(
        self,
        novel_id: str,
        payload: NovelEntityCreate,
    ) -> NovelEntity:
        return self.storage.create_entity(
            novel_id,
            payload,
        )

    def list_entities(
        self,
        novel_id: str,
        *,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NovelEntity]:
        return self.storage.list_entities(
            novel_id,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )

    def get_entity(
        self,
        novel_id: str,
        entity_id: str,
    ) -> NovelEntity:
        return self.storage.get_entity(
            novel_id,
            entity_id,
        )

    def update_entity(
        self,
        novel_id: str,
        entity_id: str,
        payload: NovelEntityUpdate,
    ) -> NovelEntity:
        return self.storage.update_entity(
            novel_id,
            entity_id,
            payload,
        )

    def resolve_entity(
        self,
        novel_id: str,
        payload: EntityResolveRequest,
    ) -> EntityResolution:
        return self.storage.resolve_entity(
            novel_id,
            payload,
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
        *,
        expected_project_revision: int | None = None,
        expected_story_bible_revision: int | None = None,
    ) -> NovelPlan:
        return self.storage.update_novel_plan(
            novel_id,
            payload,
            expected_project_revision=expected_project_revision,
            expected_story_bible_revision=expected_story_bible_revision,
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

    def create_story_arc(
        self,
        novel_id: str,
        payload: StoryArcCreate,
        *,
        expected_project_revision: int | None = None,
        expected_story_bible_revision: int | None = None,
        expected_novel_plan_revision: int | None = None,
    ) -> StoryArc:
        return self.storage.create_story_arc(
            novel_id,
            payload,
            expected_project_revision=expected_project_revision,
            expected_story_bible_revision=expected_story_bible_revision,
            expected_novel_plan_revision=expected_novel_plan_revision,
        )

    def list_story_arcs(
        self,
        novel_id: str,
        *,
        volume_number: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoryArc]:
        return self.storage.list_story_arcs(
            novel_id,
            volume_number=volume_number,
            limit=limit,
            offset=offset,
        )

    def get_story_arc(
        self,
        novel_id: str,
        arc_id: str,
    ) -> StoryArc:
        return self.storage.get_story_arc(
            novel_id,
            arc_id,
        )

    def update_story_arc(
        self,
        novel_id: str,
        arc_id: str,
        payload: StoryArcUpdate,
    ) -> StoryArc:
        return self.storage.update_story_arc(
            novel_id,
            arc_id,
            payload,
        )

    def list_story_arc_revisions(
        self,
        novel_id: str,
        arc_id: str,
        *,
        limit: int = 100,
    ) -> list[StoryArcRevision]:
        return self.storage.list_story_arc_revisions(
            novel_id,
            arc_id,
            limit=limit,
        )

    def get_story_arc_revision(
        self,
        novel_id: str,
        arc_id: str,
        revision: int,
    ) -> StoryArcRevision:
        return self.storage.get_story_arc_revision(
            novel_id,
            arc_id,
            revision,
        )

    def create_chapter_plan(
        self,
        novel_id: str,
        payload: ChapterPlanCreate,
        *,
        expected_project_revision: int | None = None,
        expected_story_bible_revision: int | None = None,
        expected_novel_plan_revision: int | None = None,
        expected_story_arc_revision: int | None = None,
    ) -> ChapterPlan:
        return self.storage.create_chapter_plan(
            novel_id,
            payload,
            expected_project_revision=expected_project_revision,
            expected_story_bible_revision=expected_story_bible_revision,
            expected_novel_plan_revision=expected_novel_plan_revision,
            expected_story_arc_revision=expected_story_arc_revision,
        )

    def list_chapter_plans(
        self,
        novel_id: str,
        *,
        arc_id: str | None = None,
        volume_number: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChapterPlan]:
        return self.storage.list_chapter_plans(
            novel_id,
            arc_id=arc_id,
            volume_number=volume_number,
            limit=limit,
            offset=offset,
        )

    def get_chapter_plan(
        self,
        novel_id: str,
        chapter_plan_id: str,
    ) -> ChapterPlan:
        return self.storage.get_chapter_plan(
            novel_id,
            chapter_plan_id,
        )

    def update_chapter_plan(
        self,
        novel_id: str,
        chapter_plan_id: str,
        payload: ChapterPlanUpdate,
    ) -> ChapterPlan:
        return self.storage.update_chapter_plan(
            novel_id,
            chapter_plan_id,
            payload,
        )

    def list_chapter_plan_revisions(
        self,
        novel_id: str,
        chapter_plan_id: str,
        *,
        limit: int = 100,
    ) -> list[ChapterPlanRevision]:
        return self.storage.list_chapter_plan_revisions(
            novel_id,
            chapter_plan_id,
            limit=limit,
        )

    def get_chapter_plan_revision(
        self,
        novel_id: str,
        chapter_plan_id: str,
        revision: int,
    ) -> ChapterPlanRevision:
        return self.storage.get_chapter_plan_revision(
            novel_id,
            chapter_plan_id,
            revision,
        )
