from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from app.agents.planner_agent import PlannerAgent
from app.novels.schemas import (
    ChapterPlanCreate,
    NovelPlanUpdate,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryArcCreate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.planner.parser import (
    PlannerOutputError,
    parse_candidate,
)
from app.planner.schemas import PlannerGenerateRequest
from app.planner.service import (
    PlannerCoordinateError,
    PlannerService,
    PlannerSourceStaleError,
)


class FakeAgentManager:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, object]] = []

    async def execute(
        self,
        agent_name: str,
        context,
    ):
        self.calls.append((agent_name, context))
        return SimpleNamespace(
            content=self.content,
            provider=context.provider,
            model=context.model or "qwen3:8b",
            finish_reason="stop",
            usage=None,
            latency_ms=12.5,
            metadata={
                "execution_mode": "structured_planning",
                "llm_called": True,
            },
        )


class PlannerParserTests(unittest.TestCase):
    def test_parse_plain_json(self) -> None:
        candidate = parse_candidate(
            "novel_plan",
            json.dumps(
                {
                    "story_premise": "Premise",
                    "themes": ["identity"],
                }
            ),
        )
        self.assertEqual(candidate.story_premise, "Premise")
        self.assertEqual(candidate.themes, ["identity"])

    def test_parse_fenced_json(self) -> None:
        candidate = parse_candidate(
            "story_arc",
            "```json\n"
            + json.dumps(
                {
                    "volume_number": 1,
                    "arc_number": 2,
                    "title": "Arc",
                }
            )
            + "\n```",
        )
        self.assertEqual(candidate.volume_number, 1)
        self.assertEqual(candidate.arc_number, 2)

    def test_parse_json_from_surrounding_text(self) -> None:
        candidate = parse_candidate(
            "chapter_plan",
            "result: "
            + json.dumps(
                {
                    "arc_id": "arc-1",
                    "chapter_number": 7,
                    "title": "Chapter",
                }
            )
            + " done",
        )
        self.assertEqual(candidate.chapter_number, 7)

    def test_invalid_json_raises_output_error(self) -> None:
        with self.assertRaises(PlannerOutputError):
            parse_candidate(
                "novel_plan",
                "not json",
            )

    def test_candidate_extra_field_is_rejected(self) -> None:
        with self.assertRaises(PlannerOutputError):
            parse_candidate(
                "chapter_plan",
                json.dumps(
                    {
                        "arc_id": "arc-1",
                        "chapter_number": 1,
                        "title": "Chapter",
                        "unexpected": True,
                    }
                ),
            )


class PlannerRequestTests(unittest.TestCase):
    def test_story_arc_requires_coordinates(self) -> None:
        with self.assertRaises(ValidationError):
            PlannerGenerateRequest(
                target="story_arc",
                instruction="Generate arc",
            )

    def test_chapter_plan_requires_arc_and_number(self) -> None:
        with self.assertRaises(ValidationError):
            PlannerGenerateRequest(
                target="chapter_plan",
                instruction="Generate chapter plan",
                arc_id="arc-1",
            )


class PlannerAgentIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = PlannerAgent(
            llm_manager=SimpleNamespace()
        )

    def test_planner_agent_identity(self) -> None:
        self.assertEqual(self.agent.name, "planner")

    def test_planner_agent_execution_mode(self) -> None:
        self.assertEqual(
            self.agent.execution_mode,
            "structured_planning",
        )

    def test_planner_agent_recommends_medium_reasoning(self) -> None:
        self.assertEqual(
            self.agent.recommended_reasoning_effort,
            "medium",
        )


class PlannerServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = str(
            Path(self.temp_dir.name) / "novels.db"
        )
        self.novel_service = NovelProjectService(
            NovelProjectStorage(db_path=db_path)
        )
        self.project = self.novel_service.create_project(
            NovelProjectCreate(
                user_id="planner-user",
                title="Planner Test",
                genre="science fiction",
                premise="A lost fleet returns home.",
            )
        )
        self.novel_id = self.project.novel_id
        self.plan = self.novel_service.update_novel_plan(
            self.novel_id,
            NovelPlanUpdate(
                expected_revision=1,
                story_premise="The lost fleet returns.",
                core_conflict="History denies the fleet.",
            ),
        )
        self.arc = self.novel_service.create_story_arc(
            self.novel_id,
            StoryArcCreate(
                volume_number=1,
                arc_number=1,
                title="Return Review",
                objective="Establish the identity conflict.",
            ),
        )
        self.chapter = self.novel_service.create_chapter_plan(
            self.novel_id,
            ChapterPlanCreate(
                arc_id=self.arc.arc_id,
                chapter_number=1,
                title="Arrival",
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _service(
        self,
        payload: dict,
    ) -> tuple[PlannerService, FakeAgentManager]:
        manager = FakeAgentManager(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )
        return (
            PlannerService(
                novel_service=self.novel_service,
                agent_manager=manager,
            ),
            manager,
        )

    async def test_generate_novel_plan_candidate(self) -> None:
        service, manager = self._service(
            {
                "story_premise": "Replanned premise",
                "core_conflict": "Identity versus records",
                "themes": ["identity", "history"],
            }
        )
        result = await service.generate(
            self.novel_id,
            PlannerGenerateRequest(
                target="novel_plan",
                instruction="Replan the novel.",
                use_memory=False,
            ),
        )
        self.assertEqual(result.target, "novel_plan")
        self.assertEqual(
            result.candidate.story_premise,
            "Replanned premise",
        )
        self.assertFalse(result.persisted)
        self.assertEqual(manager.calls[0][0], "planner")

    async def test_generate_story_arc_candidate(self) -> None:
        service, _ = self._service(
            {
                "volume_number": 1,
                "arc_number": 2,
                "title": "Archive Trail",
                "objective": "Find the first original record.",
            }
        )
        result = await service.generate(
            self.novel_id,
            PlannerGenerateRequest(
                target="story_arc",
                instruction="Plan the next arc.",
                volume_number=1,
                arc_number=2,
                use_memory=False,
            ),
        )
        self.assertEqual(result.candidate.arc_number, 2)
        self.assertEqual(
            result.source_revisions.novel_plan_revision,
            2,
        )

    async def test_generate_chapter_plan_candidate(self) -> None:
        service, _ = self._service(
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 2,
                "title": "Isolation",
                "objective": "Increase pressure.",
                "scene_beats": [
                    {
                        "beat_id": "beat-1",
                        "order": 1,
                        "title": "Transfer",
                    }
                ],
            }
        )
        result = await service.generate(
            self.novel_id,
            PlannerGenerateRequest(
                target="chapter_plan",
                instruction="Plan chapter two.",
                arc_id=self.arc.arc_id,
                chapter_number=2,
                use_memory=False,
            ),
        )
        self.assertEqual(result.candidate.chapter_number, 2)
        self.assertEqual(len(result.candidate.scene_beats), 1)

    async def test_source_revisions_are_captured(self) -> None:
        service, _ = self._service(
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 2,
                "title": "Isolation",
            }
        )
        result = await service.generate(
            self.novel_id,
            PlannerGenerateRequest(
                target="chapter_plan",
                instruction="Plan chapter two.",
                arc_id=self.arc.arc_id,
                chapter_number=2,
                use_memory=False,
            ),
        )
        revisions = result.source_revisions
        self.assertEqual(revisions.project_revision, 1)
        self.assertEqual(revisions.story_bible_revision, 1)
        self.assertEqual(revisions.novel_plan_revision, 2)
        self.assertEqual(revisions.story_arc_revision, 1)

    async def test_generation_does_not_persist_candidate(self) -> None:
        before_plan = self.novel_service.get_novel_plan(
            self.novel_id
        )
        before_arcs = self.novel_service.list_story_arcs(
            self.novel_id
        )
        before_chapters = self.novel_service.list_chapter_plans(
            self.novel_id
        )

        service, _ = self._service(
            {
                "story_premise": "Candidate only",
            }
        )
        await service.generate(
            self.novel_id,
            PlannerGenerateRequest(
                target="novel_plan",
                instruction="Generate a candidate only.",
                use_memory=False,
            ),
        )

        after_plan = self.novel_service.get_novel_plan(
            self.novel_id
        )
        after_arcs = self.novel_service.list_story_arcs(
            self.novel_id
        )
        after_chapters = self.novel_service.list_chapter_plans(
            self.novel_id
        )

        self.assertEqual(after_plan.revision, before_plan.revision)
        self.assertEqual(len(after_arcs), len(before_arcs))
        self.assertEqual(len(after_chapters), len(before_chapters))

    async def test_story_arc_generation_rejects_stale_plan(self) -> None:
        self.novel_service.update_project(
            self.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                genre="hard science fiction",
            ),
        )
        service, _ = self._service(
            {
                "volume_number": 1,
                "arc_number": 2,
                "title": "Arc",
            }
        )
        with self.assertRaises(PlannerSourceStaleError):
            await service.generate(
                self.novel_id,
                PlannerGenerateRequest(
                    target="story_arc",
                    instruction="Plan next arc.",
                    volume_number=1,
                    arc_number=2,
                    use_memory=False,
                ),
            )

    async def test_chapter_generation_rejects_stale_arc(self) -> None:
        self.novel_service.update_novel_plan(
            self.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                central_question="Who owns history?",
            ),
        )
        service, _ = self._service(
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 2,
                "title": "Chapter",
            }
        )
        with self.assertRaises(PlannerSourceStaleError):
            await service.generate(
                self.novel_id,
                PlannerGenerateRequest(
                    target="chapter_plan",
                    instruction="Plan next chapter.",
                    arc_id=self.arc.arc_id,
                    chapter_number=2,
                    use_memory=False,
                ),
            )

    async def test_story_arc_fixed_coordinates_are_enforced(self) -> None:
        service, _ = self._service(
            {
                "volume_number": 2,
                "arc_number": 9,
                "title": "Wrong position",
            }
        )
        with self.assertRaises(PlannerCoordinateError):
            await service.generate(
                self.novel_id,
                PlannerGenerateRequest(
                    target="story_arc",
                    instruction="Plan next arc.",
                    volume_number=1,
                    arc_number=2,
                    use_memory=False,
                ),
            )

    async def test_chapter_fixed_coordinates_are_enforced(self) -> None:
        service, _ = self._service(
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 99,
                "title": "Wrong chapter",
            }
        )
        with self.assertRaises(PlannerCoordinateError):
            await service.generate(
                self.novel_id,
                PlannerGenerateRequest(
                    target="chapter_plan",
                    instruction="Plan chapter two.",
                    arc_id=self.arc.arc_id,
                    chapter_number=2,
                    use_memory=False,
                ),
            )

    async def test_chapter_prompt_uses_target_aware_context(self) -> None:
        service, manager = self._service(
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 2,
                "title": "Isolation",
            }
        )

        result = await service.generate(
            self.novel_id,
            PlannerGenerateRequest(
                target="chapter_plan",
                instruction="Plan chapter two.",
                arc_id=self.arc.arc_id,
                chapter_number=2,
                use_memory=False,
            ),
        )

        self.assertEqual(
            result.metadata["planner_context_mode"],
            "target_aware_compact",
        )
        self.assertLessEqual(
            result.metadata["planner_context_chars"],
            service.CONTEXT_CHAR_BUDGET,
        )

        instruction = manager.calls[0][1].instruction
        payload = json.loads(
            instruction.split("\n\n", 1)[1]
        )

        context = payload[
            "authoritative_context"
        ]

        self.assertIn(
            "selected_story_arc",
            context,
        )
        self.assertIn(
            "nearby_chapter_plans",
            context,
        )
        self.assertNotIn(
            "story_arcs",
            context,
        )
        self.assertNotIn(
            "chapter_plans",
            context,
        )

        schema = payload[
            "candidate_json_schema"
        ]

        self.assertNotIn(
            "title",
            schema,
        )
        self.assertIn(
            "title",
            schema["properties"],
        )
        self.assertNotIn(
            "maxLength",
            schema["properties"]["title"],
        )

    def test_planner_context_is_bounded(self) -> None:
        service, _ = self._service(
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 2,
                "title": "Isolation",
            }
        )

        dense_nested_context = {
            f"group_{group_index}": {
                f"entry_{entry_index}": [
                    "设" * 20_000,
                    "定" * 20_000,
                ]
                for entry_index in range(6)
            }
            for group_index in range(6)
        }

        raw_context = {
            "project": {
                "novel_id": self.novel_id,
                "revision": self.project.revision,
                "premise": "设" * 20_000,
                "constraints": [
                    "约束" * 2_000
                    for _ in range(30)
                ],
                "style_guide": dense_nested_context,
            },
            "story_bible": {
                "novel_id": self.novel_id,
                "revision": 1,
                "world": {
                    f"rule_{index}": (
                        "世界规则" * 1_000
                    )
                    for index in range(30)
                },
                "characters": [
                    {
                        "name": f"Character {index}",
                        "history": "经历" * 2_000,
                    }
                    for index in range(30)
                ],
                "rules": dense_nested_context,
            },
            "novel_plan": {
                "novel_id": self.novel_id,
                "revision": self.plan.revision,
                "story_premise": "主线" * 5_000,
                "main_plot": [
                    {
                        "beat_id": f"beat-{index}",
                        "summary": "剧情" * 2_000,
                    }
                    for index in range(30)
                ],
                "volume_plans": dense_nested_context,
            },
            "selected_story_arc": {
                "arc_id": self.arc.arc_id,
                "novel_id": self.novel_id,
                "volume_number": 1,
                "arc_number": 1,
                "revision": self.arc.revision,
                "title": self.arc.title,
                "summary": "故事弧" * 5_000,
                "turning_points": [
                    {
                        "turning_point_id": (
                            f"tp-{index}"
                        ),
                        "description": (
                            "转折" * 2_000
                        ),
                    }
                    for index in range(30)
                ],
                "character_progression": (
                    dense_nested_context
                ),
            },
        }

        compacted = service._fit_context(
            raw_context
        )

        encoded = json.dumps(
            compacted,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        self.assertLessEqual(
            len(encoded),
            service.CONTEXT_CHAR_BUDGET,
        )
        self.assertEqual(
            set(compacted),
            set(raw_context),
        )
        self.assertEqual(
            compacted["selected_story_arc"]["arc_id"],
            self.arc.arc_id,
        )
        self.assertEqual(
            compacted["selected_story_arc"]["revision"],
            self.arc.revision,
        )

        request = PlannerGenerateRequest(
            target="chapter_plan",
            instruction="Plan chapter two.",
            arc_id=self.arc.arc_id,
            chapter_number=2,
            use_memory=False,
        )

        instruction = service._instruction(
            request,
            compacted,
        )

        payload = json.loads(
            instruction.split("\n\n", 1)[1]
        )

        self.assertEqual(
            payload["fixed_coordinates"],
            {
                "arc_id": self.arc.arc_id,
                "chapter_number": 2,
            },
        )
        schema = payload["candidate_json_schema"]
        self.assertIn("properties", schema)
        self.assertIn("required", schema)
        self.assertIn("arc_id", schema["properties"])
        self.assertIn("arc_id", schema["required"])
        self.assertLess(
            len(instruction),
            8_000,
        )


class PlannerSurfaceTests(unittest.TestCase):
    def test_planner_creates_no_database_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = NovelProjectStorage(
                db_path=str(
                    Path(temp_dir) / "novels.db"
                )
            )
            with storage._connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }

        self.assertNotIn("planner_candidates", tables)
        self.assertNotIn("planner_runs", tables)


if __name__ == "__main__":
    unittest.main()
