from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Any

from app.novels.schemas import ChapterPlan
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectNotFoundError

from .schemas import ChapterWorkflowRequest


class ChapterWorkflowGroundingNotFoundError(LookupError):
    """The workflow's explicit planning binding does not exist."""


class ChapterWorkflowGroundingConflictError(RuntimeError):
    """The planning binding is stale or no longer current."""


@dataclass(frozen=True)
class ChapterWorkflowGrounding:
    message: str
    metadata: dict[str, Any]


class ChapterWorkflowGroundingService:
    """Resolve a fresh Chapter Plan into bounded Agent grounding."""

    CONTEXT_CHAR_BUDGET = 3600
    ADJACENT_PREVIOUS_LIMIT = 2
    ADJACENT_NEXT_LIMIT = 1
    CHAPTER_SCAN_LIMIT = 1000
    ACTIVE_ENTITY_LIMIT = 32

    _PREFIX = (
        "[GROUNDED CHAPTER PLAN - MUST FOLLOW]\n"
        "This is P0.3 authoritative planning context for the current "
        "chapter workflow.\n"
        "Follow the selected Chapter Plan coordinates, POV, objective, "
        "scene beats, continuity dependencies, and target word count.\n"
        "Canon remains P0 and overrides conflicts. Memory/RAG is supporting "
        "evidence and must not override this plan or Canon.\n"
    )

    _DROP_KEYS = {
        "metadata",
        "created_at",
        "updated_at",
        "is_stale",
    }

    _PRIORITY_KEYS = (
        "priority",
        "binding",
        "source_revisions",
        "active_entities",
        "project",
        "story_bible",
        "novel_plan",
        "story_arc",
        "chapter_plan",
        "adjacent_chapter_plans",
        "novel_id",
        "chapter_plan_id",
        "chapter_plan_revision",
        "arc_id",
        "volume_number",
        "arc_number",
        "chapter_number",
        "revision",
        "source_project_revision",
        "source_story_bible_revision",
        "source_novel_plan_revision",
        "source_story_arc_revision",
        "pov_character_id",
        "pov_character_name",
        "scene_beats",
        "continuity_dependencies",
        "target_word_count",
        "title",
        "objective",
        "summary",
        "premise",
        "constraints",
        "style_guide",
        "world",
        "rules",
        "themes",
        "selected_volume_plan",
        "opening_state",
        "closing_state",
        "conflict",
        "reveal",
        "hook",
        "core_conflict",
        "stakes",
        "turning_points",
        "character_progression",
        "plot_threads",
        "dependencies",
    )

    def __init__(
        self,
        novel_service: NovelProjectService | None = None,
    ) -> None:
        self.novel_service = novel_service or NovelProjectService()

    @staticmethod
    def has_binding(request: ChapterWorkflowRequest) -> bool:
        return (
            request.chapter_plan_id is not None
            and request.chapter_plan_revision is not None
        )

    @staticmethod
    def _dump(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    @classmethod
    def _compact(
        cls,
        value: Any,
        *,
        text_limit: int,
        list_limit: int,
        dict_limit: int,
    ) -> Any:
        value = cls._dump(value)

        if isinstance(value, str):
            if len(value) <= text_limit:
                return value
            return value[:text_limit].rstrip() + "…"

        if isinstance(value, list):
            return [
                cls._compact(
                    item,
                    text_limit=text_limit,
                    list_limit=list_limit,
                    dict_limit=dict_limit,
                )
                for item in value[:list_limit]
            ]

        if isinstance(value, dict):
            items = [
                (str(key), item)
                for key, item in value.items()
                if key not in cls._DROP_KEYS
            ]
            priority = {
                key
                for key, _ in items
                if key in cls._PRIORITY_KEYS
            }
            remaining = [
                key
                for key, _ in items
                if key not in priority
            ]
            selected = priority | set(
                remaining[: max(0, dict_limit - len(priority))]
            )
            return {
                key: cls._compact(
                    item,
                    text_limit=text_limit,
                    list_limit=list_limit,
                    dict_limit=dict_limit,
                )
                for key, item in items
                if key in selected
            }

        return value

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def _minimal_context(
        cls,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        chapter = context["chapter_plan"]
        arc = context["story_arc"]
        plan = context["novel_plan"]
        project = context["project"]
        bible = context["story_bible"]

        scene_beats = []
        for beat in chapter.get("scene_beats", [])[:4]:
            scene_beats.append(
                {
                    "beat_id": beat.get("beat_id", ""),
                    "order": beat.get("order"),
                    "title": str(beat.get("title", ""))[:96],
                    "summary": str(beat.get("summary", ""))[:160],
                    "purpose": str(beat.get("purpose", ""))[:120],
                    "character_ids": beat.get("character_ids", [])[:8],
                    "location_id": beat.get("location_id"),
                }
            )

        return {
            "priority": context["priority"],
            "binding": context["binding"],
            "source_revisions": context["source_revisions"],
            "active_entities": context["active_entities"],
            "project": {
                "revision": project["revision"],
                "title": str(project.get("title", ""))[:128],
                "genre": str(project.get("genre", ""))[:64],
                "constraints": project.get("constraints", [])[:6],
            },
            "story_bible": {
                "revision": bible["revision"],
                "rules": bible.get("rules", [])[:4],
                "themes": bible.get("themes", [])[:6],
            },
            "novel_plan": {
                "revision": plan["revision"],
                "story_premise": str(
                    plan.get("story_premise", "")
                )[:240],
                "core_conflict": str(
                    plan.get("core_conflict", "")
                )[:240],
                "central_question": str(
                    plan.get("central_question", "")
                )[:160],
            },
            "story_arc": {
                "arc_id": arc["arc_id"],
                "volume_number": arc["volume_number"],
                "arc_number": arc["arc_number"],
                "revision": arc["revision"],
                "title": str(arc.get("title", ""))[:128],
                "objective": str(arc.get("objective", ""))[:240],
                "summary": str(arc.get("summary", ""))[:240],
                "core_conflict": str(
                    arc.get("core_conflict", "")
                )[:240],
                "stakes": str(arc.get("stakes", ""))[:160],
                "turning_points": arc.get("turning_points", [])[:3],
                "character_progression": arc.get(
                    "character_progression", []
                )[:4],
            },
            "chapter_plan": {
                "chapter_plan_id": chapter["chapter_plan_id"],
                "arc_id": chapter["arc_id"],
                "chapter_number": chapter["chapter_number"],
                "revision": chapter["revision"],
                "title": str(chapter.get("title", ""))[:128],
                "objective": str(chapter.get("objective", ""))[:260],
                "summary": str(chapter.get("summary", ""))[:260],
                "pov_character_id": chapter.get("pov_character_id"),
                "pov_character_name": str(
                    chapter.get("pov_character_name", "")
                )[:96],
                "opening_state": str(
                    chapter.get("opening_state", "")
                )[:180],
                "closing_state": str(
                    chapter.get("closing_state", "")
                )[:180],
                "conflict": str(chapter.get("conflict", ""))[:220],
                "reveal": str(chapter.get("reveal", ""))[:180],
                "hook": str(chapter.get("hook", ""))[:180],
                "scene_beats": scene_beats,
                "continuity_dependencies": chapter.get(
                    "continuity_dependencies", []
                )[:8],
                "target_word_count": chapter.get("target_word_count", 0),
            },
            "adjacent_chapter_plans": context[
                "adjacent_chapter_plans"
            ][:3],
        }

    @classmethod
    def _render_context(
        cls,
        context: dict[str, Any],
    ) -> str:
        json_budget = cls.CONTEXT_CHAR_BUDGET - len(cls._PREFIX)
        passes = (
            (520, 12, 22),
            (360, 10, 18),
            (240, 8, 16),
            (160, 6, 14),
            (96, 4, 12),
            (64, 3, 10),
        )

        for text_limit, list_limit, dict_limit in passes:
            compacted = cls._compact(
                context,
                text_limit=text_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            encoded = cls._json(compacted)
            if len(encoded) <= json_budget:
                return cls._PREFIX + encoded

        minimal = cls._minimal_context(context)
        for text_limit, list_limit, dict_limit in (
            (96, 4, 14),
            (64, 3, 12),
            (40, 2, 10),
        ):
            compacted = cls._compact(
                minimal,
                text_limit=text_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            encoded = cls._json(compacted)
            if len(encoded) <= json_budget:
                return cls._PREFIX + encoded

        core = {
            "priority": context["priority"],
            "binding": context["binding"],
            "source_revisions": context["source_revisions"],
            "active_entities": {
                "pov_character_id": context["active_entities"].get(
                    "pov_character_id"
                ),
                "active_entity_ids": context["active_entities"].get(
                    "active_entity_ids", []
                )[:8],
                "active_character_ids": context["active_entities"].get(
                    "active_character_ids", []
                )[:8],
                "active_location_ids": context["active_entities"].get(
                    "active_location_ids", []
                )[:8],
            },
        }
        encoded = cls._json(
            cls._compact(
                core,
                text_limit=64,
                list_limit=8,
                dict_limit=12,
            )
        )
        return cls._PREFIX + encoded

    @staticmethod
    def _chapter_summary(chapter: ChapterPlan) -> dict[str, Any]:
        return {
            "chapter_plan_id": chapter.chapter_plan_id,
            "arc_id": chapter.arc_id,
            "chapter_number": chapter.chapter_number,
            "revision": chapter.revision,
            "title": chapter.title,
            "objective": chapter.objective,
            "summary": chapter.summary,
            "closing_state": chapter.closing_state,
            "hook": chapter.hook,
            "pov_character_id": chapter.pov_character_id,
        }

    @classmethod
    def _adjacent_chapters(
        cls,
        chapters: list[ChapterPlan],
        selected: ChapterPlan,
    ) -> list[dict[str, Any]]:
        fresh = [
            item
            for item in chapters
            if item.chapter_plan_id != selected.chapter_plan_id
            and not item.is_stale
        ]
        previous = [
            item
            for item in fresh
            if item.chapter_number < selected.chapter_number
        ][-cls.ADJACENT_PREVIOUS_LIMIT :]
        following = [
            item
            for item in fresh
            if item.chapter_number > selected.chapter_number
        ][: cls.ADJACENT_NEXT_LIMIT]
        return [
            cls._chapter_summary(item)
            for item in previous + following
        ]

    @staticmethod
    def _active_entities(
        chapter: ChapterPlan,
    ) -> tuple[list[str], list[str], list[str]]:
        character_ids: list[str] = []
        location_ids: list[str] = []

        def add(target: list[str], value: Any) -> None:
            cleaned = str(value or "").strip()
            if (
                cleaned
                and cleaned not in target
                and len(target)
                < ChapterWorkflowGroundingService.ACTIVE_ENTITY_LIMIT
            ):
                target.append(cleaned)

        add(character_ids, chapter.pov_character_id)
        for beat in chapter.scene_beats:
            for character_id in beat.character_ids:
                add(character_ids, character_id)
            add(location_ids, beat.location_id)

        entity_ids = character_ids + [
            value
            for value in location_ids
            if value not in character_ids
        ]
        entity_ids = entity_ids[
            : ChapterWorkflowGroundingService.ACTIVE_ENTITY_LIMIT
        ]
        return entity_ids, character_ids, location_ids

    def resolve(
        self,
        request: ChapterWorkflowRequest,
    ) -> ChapterWorkflowGrounding:
        if not self.has_binding(request):
            raise ChapterWorkflowGroundingConflictError(
                "Chapter Workflow requires chapter_plan_id and "
                "chapter_plan_revision."
            )

        assert request.chapter_plan_id is not None
        assert request.chapter_plan_revision is not None

        try:
            project = self.novel_service.get_project(request.novel_id)
            bible = self.novel_service.get_story_bible(request.novel_id)
            plan = self.novel_service.get_novel_plan(request.novel_id)
            chapter = self.novel_service.get_chapter_plan(
                request.novel_id,
                request.chapter_plan_id,
            )
            arc = self.novel_service.get_story_arc(
                request.novel_id,
                chapter.arc_id,
            )
            chapters = self.novel_service.list_chapter_plans(
                request.novel_id,
                limit=self.CHAPTER_SCAN_LIMIT,
            )
        except NovelProjectNotFoundError as exc:
            raise ChapterWorkflowGroundingNotFoundError(str(exc)) from exc

        if project.user_id != request.user_id:
            raise ChapterWorkflowGroundingConflictError(
                "Workflow user_id does not own the selected Novel Project."
            )

        if chapter.revision != request.chapter_plan_revision:
            raise ChapterWorkflowGroundingConflictError(
                "Chapter Plan revision conflict: "
                f"expected={request.chapter_plan_revision}, "
                f"current={chapter.revision}."
            )

        if plan.is_stale:
            raise ChapterWorkflowGroundingConflictError(
                "Novel Plan is stale; refresh it before starting the "
                "Chapter Workflow."
            )
        if arc.is_stale:
            raise ChapterWorkflowGroundingConflictError(
                "Selected Story Arc is stale; refresh it before starting "
                "the Chapter Workflow."
            )
        if chapter.is_stale:
            raise ChapterWorkflowGroundingConflictError(
                "Selected Chapter Plan is stale; refresh it before starting "
                "the Chapter Workflow."
            )

        active_ids, character_ids, location_ids = self._active_entities(
            chapter
        )
        selected_volume = [
            item.model_dump(mode="json")
            for item in plan.volume_plans
            if item.volume_number == arc.volume_number
        ][:1]

        context = {
            "priority": "P0.3_CHAPTER_WORKFLOW_GROUNDING",
            "binding": {
                "novel_id": request.novel_id,
                "chapter_plan_id": chapter.chapter_plan_id,
                "chapter_plan_revision": chapter.revision,
                "arc_id": chapter.arc_id,
                "chapter_number": chapter.chapter_number,
            },
            "source_revisions": {
                "project_revision": project.revision,
                "story_bible_revision": bible.revision,
                "novel_plan_revision": plan.revision,
                "story_arc_revision": arc.revision,
                "chapter_plan_revision": chapter.revision,
            },
            "active_entities": {
                "pov_character_id": chapter.pov_character_id,
                "active_entity_ids": active_ids,
                "active_character_ids": character_ids,
                "active_location_ids": location_ids,
            },
            "project": {
                "novel_id": project.novel_id,
                "revision": project.revision,
                "title": project.title,
                "genre": project.genre,
                "premise": project.premise,
                "language": project.language,
                "target_word_count": project.target_word_count,
                "constraints": project.constraints,
                "style_guide": project.style_guide,
            },
            "story_bible": {
                "novel_id": bible.novel_id,
                "revision": bible.revision,
                "world": bible.world,
                "rules": bible.rules,
                "themes": bible.themes,
            },
            "novel_plan": {
                "novel_id": plan.novel_id,
                "revision": plan.revision,
                "source_project_revision": plan.source_project_revision,
                "source_story_bible_revision": (
                    plan.source_story_bible_revision
                ),
                "story_premise": plan.story_premise,
                "core_conflict": plan.core_conflict,
                "central_question": plan.central_question,
                "ending_direction": plan.ending_direction,
                "themes": plan.themes,
                "selected_volume_plan": selected_volume,
            },
            "story_arc": self._dump(arc),
            "chapter_plan": self._dump(chapter),
            "adjacent_chapter_plans": self._adjacent_chapters(
                chapters,
                chapter,
            ),
        }
        message = self._render_context(context)
        memory_query = " | ".join(
            value
            for value in (
                f"Chapter {chapter.chapter_number}: {chapter.title}",
                chapter.objective,
                chapter.summary,
                "POV: " + (
                    chapter.pov_character_name
                    or str(chapter.pov_character_id or "")
                ),
                "Continuity: "
                + ", ".join(chapter.continuity_dependencies[:12]),
            )
            if value.strip(" |:")
        )[:1200]

        metadata = {
            "grounding_mode": "chapter_plan",
            "grounding_context_chars": len(message),
            "chapter_plan_id": chapter.chapter_plan_id,
            "chapter_plan_revision": chapter.revision,
            "chapter_number": chapter.chapter_number,
            "story_arc_id": arc.arc_id,
            "story_arc_revision": arc.revision,
            "novel_plan_revision": plan.revision,
            "source_project_revision": project.revision,
            "source_story_bible_revision": bible.revision,
            "pov_character_id": chapter.pov_character_id,
            "active_entity_ids": active_ids,
            "active_character_ids": character_ids,
            "active_location_ids": location_ids,
            "adjacent_chapter_plan_ids": [
                item["chapter_plan_id"]
                for item in context["adjacent_chapter_plans"]
            ],
            "memory_query": memory_query,
            "planning_freshness_validated": True,
        }
        return ChapterWorkflowGrounding(
            message=message,
            metadata=metadata,
        )


chapter_workflow_grounding_service = ChapterWorkflowGroundingService()
