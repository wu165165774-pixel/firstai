from __future__ import annotations

import json
from typing import Any

from app.agents.manager import AgentManager
from app.agents.schemas import AgentContext
from app.novels.schemas import (
    ChapterPlan,
    ChapterPlanCreate,
    NovelPlan,
    NovelPlanUpdate,
    NovelProject,
    StoryArc,
    StoryArcCreate,
    StoryBible,
)
from app.novels.service import NovelProjectService

from .parser import (
    PlannerOutputError,
    candidate_model,
    parse_candidate,
)
from .schemas import (
    ChapterPlanCandidate,
    PlannerAcceptRequest,
    PlannerAcceptResult,
    PlannerGenerateRequest,
    PlannerGenerateResult,
    PlannerSourceRevisions,
    NovelPlanCandidate,
    StoryArcCandidate,
)


class PlannerSourceStaleError(RuntimeError):
    pass


class PlannerCoordinateError(ValueError):
    pass


class PlannerAcceptanceConflictError(RuntimeError):
    pass


class PlannerService:
    CONTEXT_CHAR_BUDGET = 3600
    STORY_ARC_INDEX_LIMIT = 24
    NEARBY_CHAPTER_LIMIT = 12

    _CONTEXT_DROP_KEYS = {
        "metadata",
        "created_at",
        "updated_at",
        "is_stale",
    }

    _CONTEXT_PRIORITY_KEYS = (
        "novel_id",
        "arc_id",
        "chapter_plan_id",
        "beat_id",
        "turning_point_id",
        "character_id",
        "volume_number",
        "arc_number",
        "chapter_number",
        "order",
        "revision",
        "story_bible_revision",
        "source_project_revision",
        "source_story_bible_revision",
        "source_novel_plan_revision",
        "source_story_arc_revision",
        "title",
    )

    _SCHEMA_DROP_KEYS = {
        "title",
        "description",
        "default",
        "examples",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }

    def __init__(
        self,
        novel_service: NovelProjectService | None = None,
        agent_manager: AgentManager | None = None,
    ) -> None:
        self.novel_service = novel_service or NovelProjectService()

        if agent_manager is None:
            from .bootstrap import planner_agent_manager

            agent_manager = planner_agent_manager

        self.agent_manager = agent_manager

    @staticmethod
    def _dump_model(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    @classmethod
    def _compact_value(
        cls,
        value: Any,
        *,
        text_limit: int,
        list_limit: int,
        dict_limit: int,
    ) -> Any:
        value = cls._dump_model(value)

        if isinstance(value, str):
            if len(value) <= text_limit:
                return value
            return value[:text_limit].rstrip() + "…"

        if isinstance(value, list):
            return [
                cls._compact_value(
                    item,
                    text_limit=text_limit,
                    list_limit=list_limit,
                    dict_limit=dict_limit,
                )
                for item in value[:list_limit]
            ]

        if isinstance(value, dict):
            result: dict[str, Any] = {}
            items = [
                (key, item)
                for key, item in value.items()
                if key not in cls._CONTEXT_DROP_KEYS
            ]
            priority = {
                key
                for key, _ in items
                if key in cls._CONTEXT_PRIORITY_KEYS
            }
            regular_slots = max(
                0,
                dict_limit - len(priority),
            )
            regular = [
                key
                for key, _ in items
                if key not in priority
            ]
            selected = priority | set(
                regular[:regular_slots]
            )

            for key, item in items:
                if key not in selected:
                    continue

                result[key] = cls._compact_value(
                    item,
                    text_limit=text_limit,
                    list_limit=list_limit,
                    dict_limit=dict_limit,
                )

            return result

        return value

    @staticmethod
    def _json_chars(value: Any) -> int:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    @classmethod
    def _fit_value_to_budget(
        cls,
        value: Any,
        budget: int,
    ) -> Any:
        if cls._json_chars(value) <= budget:
            return value

        if isinstance(value, str):
            if budget < 2:
                return ""

            low = 0
            high = len(value)
            fitted = ""

            while low <= high:
                middle = (low + high) // 2
                candidate = value[:middle].rstrip()

                if middle < len(value):
                    candidate += "…"

                if cls._json_chars(candidate) <= budget:
                    fitted = candidate
                    low = middle + 1
                else:
                    high = middle - 1

            return fitted

        if isinstance(value, list):
            result: list[Any] = []

            for item in value:
                separator_chars = 1 if result else 0
                available = (
                    budget
                    - cls._json_chars(result)
                    - separator_chars
                )

                if available <= 0:
                    break

                fitted = cls._fit_value_to_budget(
                    item,
                    available,
                )

                if cls._json_chars(fitted) > available:
                    break

                result.append(fitted)

            return result

        if isinstance(value, dict):
            result: dict[str, Any] = {}
            priority_order = {
                key: index
                for index, key in enumerate(
                    cls._CONTEXT_PRIORITY_KEYS
                )
            }
            items = list(value.items())
            items.sort(
                key=lambda item: priority_order.get(
                    item[0],
                    len(priority_order),
                )
            )

            for key, item in items:
                separator_chars = 1 if result else 0
                key_chars = cls._json_chars(key)
                available = (
                    budget
                    - cls._json_chars(result)
                    - separator_chars
                    - key_chars
                    - 1
                )

                if available <= 0:
                    continue

                fitted = cls._fit_value_to_budget(
                    item,
                    available,
                )

                if cls._json_chars(fitted) > available:
                    continue

                result[key] = fitted

            return result

        return value

    @classmethod
    def _hard_fit_context(
        cls,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if not context:
            return {}

        shell = {
            key: {}
            for key in context
        }
        shell_value_chars = 2 * len(shell)
        structural_chars = (
            cls._json_chars(shell)
            - shell_value_chars
        )
        available = (
            cls.CONTEXT_CHAR_BUDGET
            - structural_chars
        )

        if available < shell_value_chars:
            return {}

        per_section, remainder = divmod(
            available,
            len(context),
        )
        result: dict[str, Any] = {}

        for index, (key, value) in enumerate(
            context.items()
        ):
            section_budget = per_section + (
                1 if index < remainder else 0
            )
            result[key] = cls._fit_value_to_budget(
                value,
                section_budget,
            )

        if cls._json_chars(result) > cls.CONTEXT_CHAR_BUDGET:
            return {}

        return result

    @classmethod
    def _fit_context(
        cls,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        passes = (
            (900, 12, 24),
            (650, 10, 20),
            (450, 8, 16),
            (300, 6, 14),
            (220, 5, 12),
            (160, 4, 10),
            (100, 3, 8),
            (64, 2, 6),
        )

        compacted: dict[str, Any] = {}

        for text_limit, list_limit, dict_limit in passes:
            compacted = cls._compact_value(
                context,
                text_limit=text_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )

            if (
                cls._json_chars(compacted)
                <= cls.CONTEXT_CHAR_BUDGET
            ):
                return compacted

        return cls._hard_fit_context(compacted)

    @classmethod
    def _compact_schema(
        cls,
        value: Any,
        *,
        parent_key: str | None = None,
    ) -> Any:
        if isinstance(value, list):
            return [
                cls._compact_schema(
                    item,
                    parent_key=parent_key,
                )
                for item in value
            ]

        if isinstance(value, dict):
            result: dict[str, Any] = {}

            for key, item in value.items():
                if (
                    parent_key != "properties"
                    and key in cls._SCHEMA_DROP_KEYS
                ):
                    continue

                result[key] = cls._compact_schema(
                    item,
                    parent_key=key,
                )

            return result

        return value

    @staticmethod
    def _story_arc_index_item(
        arc: StoryArc,
    ) -> dict[str, Any]:
        return {
            "arc_id": arc.arc_id,
            "volume_number": arc.volume_number,
            "arc_number": arc.arc_number,
            "title": arc.title,
            "objective": arc.objective,
            "summary": arc.summary,
            "target_chapter_start": arc.target_chapter_start,
            "target_chapter_end": arc.target_chapter_end,
        }

    @staticmethod
    def _chapter_index_item(
        chapter: ChapterPlan,
    ) -> dict[str, Any]:
        return {
            "chapter_plan_id": chapter.chapter_plan_id,
            "arc_id": chapter.arc_id,
            "volume_number": chapter.volume_number,
            "arc_number": chapter.arc_number,
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "objective": chapter.objective,
            "summary": chapter.summary,
            "pov_character_id": chapter.pov_character_id,
            "pov_character_name": chapter.pov_character_name,
            "hook": chapter.hook,
        }

    @classmethod
    def _nearby_chapters(
        cls,
        chapters: list[ChapterPlan],
        chapter_number: int,
    ) -> list[dict[str, Any]]:
        nearest = sorted(
            chapters,
            key=lambda item: (
                abs(item.chapter_number - chapter_number),
                item.chapter_number,
            ),
        )[: cls.NEARBY_CHAPTER_LIMIT]

        nearest.sort(
            key=lambda item: item.chapter_number
        )

        return [
            cls._chapter_index_item(item)
            for item in nearest
        ]

    def _build_context(
        self,
        novel_id: str,
        request: PlannerGenerateRequest,
    ) -> tuple[
        NovelProject,
        StoryBible,
        NovelPlan,
        StoryArc | None,
        dict[str, Any],
    ]:
        project = self.novel_service.get_project(novel_id)
        bible = self.novel_service.get_story_bible(novel_id)
        plan = self.novel_service.get_novel_plan(novel_id)

        selected_arc: StoryArc | None = None

        if request.target in {"story_arc", "chapter_plan"}:
            if plan.is_stale:
                raise PlannerSourceStaleError(
                    "Novel Plan is stale; refresh Novel Plan before "
                    f"generating {request.target}."
                )

        if request.target == "novel_plan":
            context = {
                "project": self._dump_model(project),
                "story_bible": self._dump_model(bible),
                "current_novel_plan": self._dump_model(plan),
            }

        elif request.target == "story_arc":
            arcs = self.novel_service.list_story_arcs(
                novel_id,
                limit=self.STORY_ARC_INDEX_LIMIT,
            )

            context = {
                "project": self._dump_model(project),
                "story_bible": self._dump_model(bible),
                "novel_plan": self._dump_model(plan),
                "existing_story_arcs": [
                    self._story_arc_index_item(item)
                    for item in arcs
                ],
            }

        else:
            assert request.target == "chapter_plan"
            assert request.arc_id is not None
            assert request.chapter_number is not None

            selected_arc = self.novel_service.get_story_arc(
                novel_id,
                request.arc_id,
            )

            if selected_arc.is_stale:
                raise PlannerSourceStaleError(
                    "Story Arc is stale; refresh Story Arc before "
                    "generating chapter_plan."
                )

            chapters = self.novel_service.list_chapter_plans(
                novel_id,
                limit=500,
            )

            context = {
                "project": self._dump_model(project),
                "story_bible": self._dump_model(bible),
                "novel_plan": self._dump_model(plan),
                "selected_story_arc": self._dump_model(
                    selected_arc
                ),
                "nearby_chapter_plans": self._nearby_chapters(
                    chapters,
                    request.chapter_number,
                ),
            }

        context = self._fit_context(context)

        return (
            project,
            bible,
            plan,
            selected_arc,
            context,
        )

    @staticmethod
    def _source_revisions(
        project: NovelProject,
        bible: StoryBible,
        plan: NovelPlan,
        selected_arc: StoryArc | None,
    ) -> PlannerSourceRevisions:
        return PlannerSourceRevisions(
            project_revision=project.revision,
            story_bible_revision=bible.revision,
            novel_plan_revision=plan.revision,
            story_arc_revision=(
                selected_arc.revision
                if selected_arc is not None
                else None
            ),
        )

    @staticmethod
    def _assert_acceptance_sources(
        expected: PlannerSourceRevisions,
        actual: PlannerSourceRevisions,
    ) -> None:
        if expected == actual:
            return

        mismatches = []
        for field in (
            "project_revision",
            "story_bible_revision",
            "novel_plan_revision",
            "story_arc_revision",
        ):
            expected_value = getattr(expected, field)
            actual_value = getattr(actual, field)
            if expected_value != actual_value:
                mismatches.append(
                    f"{field}: expected={expected_value}, "
                    f"actual={actual_value}"
                )

        raise PlannerAcceptanceConflictError(
            "Planner candidate source revisions changed; "
            + "; ".join(mismatches)
        )

    def _acceptance_sources(
        self,
        novel_id: str,
        request: PlannerAcceptRequest,
    ) -> tuple[
        NovelProject,
        StoryBible,
        NovelPlan,
        StoryArc | None,
        PlannerSourceRevisions,
    ]:
        project = self.novel_service.get_project(novel_id)
        bible = self.novel_service.get_story_bible(novel_id)
        plan = self.novel_service.get_novel_plan(novel_id)
        selected_arc: StoryArc | None = None

        if request.target in {"story_arc", "chapter_plan"}:
            if plan.is_stale:
                raise PlannerSourceStaleError(
                    "Novel Plan is stale; refresh Novel Plan before "
                    f"accepting {request.target}."
                )

        if request.target == "chapter_plan":
            assert request.arc_id is not None
            selected_arc = self.novel_service.get_story_arc(
                novel_id,
                request.arc_id,
            )
            if selected_arc.is_stale:
                raise PlannerSourceStaleError(
                    "Story Arc is stale; refresh Story Arc before "
                    "accepting chapter_plan."
                )

        actual = self._source_revisions(
            project,
            bible,
            plan,
            selected_arc,
        )
        self._assert_acceptance_sources(
            request.source_revisions,
            actual,
        )

        return project, bible, plan, selected_arc, actual

    @staticmethod
    def _fixed_coordinates(
        request: PlannerGenerateRequest,
    ) -> dict[str, Any]:
        if request.target == "story_arc":
            return {
                "volume_number": request.volume_number,
                "arc_number": request.arc_number,
            }

        if request.target == "chapter_plan":
            return {
                "arc_id": request.arc_id,
                "chapter_number": request.chapter_number,
            }

        return {}

    def _instruction(
        self,
        request: PlannerGenerateRequest,
        context: dict[str, Any],
    ) -> str:
        model = candidate_model(request.target)
        schema = self._compact_schema(
            model.model_json_schema()
        )

        payload = {
            "target": request.target,
            "author_instruction": request.instruction,
            "fixed_coordinates": self._fixed_coordinates(request),
            "candidate_json_schema": schema,
            "authoritative_context": context,
        }

        return (
            "Generate one planning candidate from the following "
            "request. Return JSON only.\n\n"
            + json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _validate_fixed_coordinates(
        request: PlannerGenerateRequest,
        candidate: Any,
    ) -> None:
        if request.target == "story_arc":
            if not isinstance(candidate, StoryArcCandidate):
                raise PlannerCoordinateError(
                    "Unexpected story_arc candidate type."
                )

            if (
                candidate.volume_number != request.volume_number
                or candidate.arc_number != request.arc_number
            ):
                raise PlannerCoordinateError(
                    "Planner changed fixed Story Arc coordinates."
                )

        if request.target == "chapter_plan":
            if not isinstance(candidate, ChapterPlanCandidate):
                raise PlannerCoordinateError(
                    "Unexpected chapter_plan candidate type."
                )

            if (
                candidate.arc_id != request.arc_id
                or candidate.chapter_number != request.chapter_number
            ):
                raise PlannerCoordinateError(
                    "Planner changed fixed Chapter Plan coordinates."
                )

    async def generate(
        self,
        novel_id: str,
        request: PlannerGenerateRequest,
    ) -> PlannerGenerateResult:
        (
            project,
            bible,
            plan,
            selected_arc,
            authoritative_context,
        ) = self._build_context(
            novel_id,
            request,
        )

        source_revisions = self._source_revisions(
            project,
            bible,
            plan,
            selected_arc,
        )

        instruction = self._instruction(
            request,
            authoritative_context,
        )

        context = AgentContext(
            user_id=project.user_id,
            novel_id=novel_id,
            instruction=instruction,
            provider=request.provider,
            model=request.model,
            use_memory=request.use_memory,
            task_mode="creative",
            reasoning_effort=request.reasoning_effort,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            metadata={
                "planner_target": request.target,
                "planner_source_revisions": (
                    source_revisions.model_dump()
                ),
                "planner_persisted": False,
                "planner_context_mode": "target_aware_compact",
                "planner_context_chars": len(
                    json.dumps(
                        authoritative_context,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
                "planner_prompt_chars": len(instruction),
            },
        )

        result = await self.agent_manager.execute(
            agent_name="planner",
            context=context,
        )

        candidate = parse_candidate(
            request.target,
            result.content,
        )

        self._validate_fixed_coordinates(
            request,
            candidate,
        )

        metadata = dict(result.metadata or {})
        metadata.update(
            {
                "planner_target": request.target,
                "candidate_validated": True,
                "persisted": False,
                "planner_context_mode": "target_aware_compact",
                "planner_context_chars": len(
                    json.dumps(
                        authoritative_context,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
                "planner_prompt_chars": len(instruction),
            }
        )

        return PlannerGenerateResult(
            target=request.target,
            candidate=candidate,
            source_revisions=source_revisions,
            provider=result.provider,
            model=result.model,
            finish_reason=result.finish_reason,
            usage=result.usage,
            latency_ms=result.latency_ms,
            metadata=metadata,
            persisted=False,
        )

    def accept(
        self,
        novel_id: str,
        request: PlannerAcceptRequest,
    ) -> PlannerAcceptResult:
        _, _, plan, _, source_revisions = self._acceptance_sources(
            novel_id,
            request,
        )

        if request.target == "novel_plan":
            assert isinstance(request.candidate, NovelPlanCandidate)
            accepted = self.novel_service.update_novel_plan(
                novel_id,
                NovelPlanUpdate(
                    expected_revision=plan.revision,
                    **request.candidate.model_dump(),
                ),
                expected_project_revision=(
                    source_revisions.project_revision
                ),
                expected_story_bible_revision=(
                    source_revisions.story_bible_revision
                ),
            )
            return PlannerAcceptResult(
                target=request.target,
                source_revisions=source_revisions,
                novel_plan=accepted,
                persisted=True,
            )

        if request.target == "story_arc":
            assert isinstance(request.candidate, StoryArcCandidate)
            accepted = self.novel_service.create_story_arc(
                novel_id,
                StoryArcCreate.model_validate(
                    request.candidate.model_dump()
                ),
                expected_project_revision=(
                    source_revisions.project_revision
                ),
                expected_story_bible_revision=(
                    source_revisions.story_bible_revision
                ),
                expected_novel_plan_revision=(
                    source_revisions.novel_plan_revision
                ),
            )
            return PlannerAcceptResult(
                target=request.target,
                source_revisions=source_revisions,
                story_arc=accepted,
                persisted=True,
            )

        assert request.target == "chapter_plan"
        assert isinstance(request.candidate, ChapterPlanCandidate)
        assert source_revisions.story_arc_revision is not None
        accepted = self.novel_service.create_chapter_plan(
            novel_id,
            ChapterPlanCreate.model_validate(
                request.candidate.model_dump()
            ),
            expected_project_revision=(
                source_revisions.project_revision
            ),
            expected_story_bible_revision=(
                source_revisions.story_bible_revision
            ),
            expected_novel_plan_revision=(
                source_revisions.novel_plan_revision
            ),
            expected_story_arc_revision=(
                source_revisions.story_arc_revision
            ),
        )
        return PlannerAcceptResult(
            target=request.target,
            source_revisions=source_revisions,
            chapter_plan=accepted,
            persisted=True,
        )
