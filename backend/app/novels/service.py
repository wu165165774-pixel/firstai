from __future__ import annotations

from typing import Any

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
    StoryBibleEntityAlignRequest,
    StoryBibleEntityAlignment,
    StoryBibleRevision,
    StoryBibleUpdate,
    normalize_entity_name,
)
from .storage import (
    NovelEntityReferenceError,
    NovelProjectNotFoundError,
    NovelProjectStorage,
)


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
        if payload.characters is not None:
            references = [
                (
                    str(character.get("entity_id") or "").strip(),
                    "character",
                    str(
                        character.get("canonical_name")
                        or character.get("name")
                        or ""
                    ).strip(),
                    f"story_bible.characters[{index}]",
                )
                for index, character in enumerate(payload.characters)
                if isinstance(character, dict)
                and character.get("entity_id")
            ]
            self._validate_entity_references(
                novel_id,
                references,
                only_when_registry_exists=False,
            )
        return self.storage.update_story_bible(
            novel_id,
            payload,
        )

    def align_story_bible_entities(
        self,
        novel_id: str,
        payload: StoryBibleEntityAlignRequest,
    ) -> StoryBibleEntityAlignment:
        return self.storage.align_story_bible_entities(
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

    def _validate_entity_references(
        self,
        novel_id: str,
        references: list[tuple[str, str, str, str]],
        *,
        only_when_registry_exists: bool = True,
    ) -> None:
        if not references:
            return

        loaded: dict[str, NovelEntity] = {}
        if only_when_registry_exists:
            enabled_types = {
                entity_type
                for _, entity_type, _, _ in references
                if self.storage.list_entities(
                    novel_id,
                    entity_type=entity_type,
                    limit=1,
                )
            }
            selected: list[tuple[str, str, str, str]] = []
            for reference in references:
                entity_id, entity_type, _, _ = reference
                try:
                    loaded[entity_id] = self.storage.get_entity(
                        novel_id,
                        entity_id,
                    )
                except NovelProjectNotFoundError:
                    if entity_type not in enabled_types:
                        continue
                selected.append(reference)
            references = selected
            if not references:
                return

        for entity_id, entity_type, display_name, source in references:
            if not entity_id:
                continue

            entity = loaded.get(entity_id)
            if entity is None:
                try:
                    entity = self.storage.get_entity(
                        novel_id,
                        entity_id,
                    )
                except NovelProjectNotFoundError as exc:
                    raise NovelEntityReferenceError(
                        "Unknown canonical entity reference: "
                        f"source={source}, entity_id={entity_id}"
                    ) from exc
                loaded[entity_id] = entity

            if entity.entity_type != entity_type:
                raise NovelEntityReferenceError(
                    "Canonical entity type mismatch: "
                    f"source={source}, entity_id={entity_id}, "
                    f"expected={entity_type}, actual={entity.entity_type}"
                )

            if display_name:
                valid_names = {
                    normalize_entity_name(entity.canonical_name),
                    *(
                        normalize_entity_name(alias)
                        for alias in entity.aliases
                    ),
                }
                if normalize_entity_name(display_name) not in valid_names:
                    raise NovelEntityReferenceError(
                        "Canonical entity ID/name conflict: "
                        f"source={source}, entity_id={entity_id}, "
                        f"name={display_name}, "
                        f"canonical_name={entity.canonical_name}"
                    )

    @staticmethod
    def _planning_entity_references(
        target: str,
        value: Any,
    ) -> list[tuple[str, str, str, str]]:
        references: list[tuple[str, str, str, str]] = []

        if target == "novel_plan":
            for beat_index, plot_beat in enumerate(
                getattr(value, "main_plot", None) or []
            ):
                for entity_index, entity_id in enumerate(
                    plot_beat.character_ids
                ):
                    references.append(
                        (
                            entity_id,
                            "character",
                            "",
                            "main_plot"
                            f"[{beat_index}].character_ids[{entity_index}]",
                        )
                    )
            for index, arc in enumerate(
                getattr(value, "character_arcs", None) or []
            ):
                references.append(
                    (
                        arc.character_id,
                        "character",
                        getattr(arc, "character_name", ""),
                        f"character_arcs[{index}]",
                    )
                )

        elif target == "story_arc":
            for index, progression in enumerate(
                getattr(value, "character_progression", None) or []
            ):
                references.append(
                    (
                        progression.character_id,
                        "character",
                        progression.character_name,
                        f"character_progression[{index}]",
                    )
                )
            for beat_index, turning_point in enumerate(
                getattr(value, "turning_points", None) or []
            ):
                for entity_index, entity_id in enumerate(
                    turning_point.character_ids
                ):
                    references.append(
                        (
                            entity_id,
                            "character",
                            "",
                            "turning_points"
                            f"[{beat_index}].character_ids[{entity_index}]",
                        )
                    )

        elif target == "chapter_plan":
            pov_character_id = getattr(
                value,
                "pov_character_id",
                None,
            )
            if pov_character_id:
                references.append(
                    (
                        pov_character_id,
                        "character",
                        getattr(value, "pov_character_name", ""),
                        "pov_character_id",
                    )
                )
            for beat_index, beat in enumerate(
                getattr(value, "scene_beats", None) or []
            ):
                for entity_index, entity_id in enumerate(
                    beat.character_ids
                ):
                    references.append(
                        (
                            entity_id,
                            "character",
                            "",
                            "scene_beats"
                            f"[{beat_index}].character_ids[{entity_index}]",
                        )
                    )
                if beat.location_id:
                    references.append(
                        (
                            beat.location_id,
                            "location",
                            "",
                            f"scene_beats[{beat_index}].location_id",
                        )
                    )

        return references

    def validate_planning_entity_references(
        self,
        novel_id: str,
        target: str,
        value: Any,
    ) -> None:
        self._validate_entity_references(
            novel_id,
            self._planning_entity_references(target, value),
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
        self.validate_planning_entity_references(
            novel_id,
            "novel_plan",
            payload,
        )
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
        self.validate_planning_entity_references(
            novel_id,
            "story_arc",
            payload,
        )
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
        self.validate_planning_entity_references(
            novel_id,
            "story_arc",
            payload,
        )
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
        self.validate_planning_entity_references(
            novel_id,
            "chapter_plan",
            payload,
        )
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
        self.validate_planning_entity_references(
            novel_id,
            "chapter_plan",
            payload,
        )
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
