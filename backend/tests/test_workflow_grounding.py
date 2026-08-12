from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI

from app.agents.novel_agent import NovelAgent
from app.agents.schemas import AgentContext
from app.llm.schemas import ChatMessage, ChatResponse
from app.novels.schemas import (
    ChapterPlanCreate,
    ChapterPlanUpdate,
    NovelEntityCreate,
    NovelPlanUpdate,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryArcCreate,
    StoryArcUpdate,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.workflows.async_executor import AsyncWorkflowExecutor
from app.workflows.chapter_workflow import ChapterWorkflow
from app.workflows.grounding import (
    ChapterWorkflowGroundingConflictError,
    ChapterWorkflowGroundingService,
)
from app.workflows.run_service import WorkflowRunService
from app.workflows.schemas import ChapterWorkflowRequest
from app.workflows.storage import WorkflowRunStorage


def agent_result(agent: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        agent=agent,
        success=True,
        content=content,
        provider="test",
        model="test-model",
        finish_reason="stop",
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
        latency_ms=1.0,
        metadata={},
    )


def approved_review() -> str:
    return json.dumps(
        {
            "approved": True,
            "summary": "Approved.",
            "scores": {
                "continuity": 90,
                "character_consistency": 90,
                "world_consistency": 90,
                "plot_logic": 90,
                "prose_quality": 90,
                "pacing": 90,
                "overall": 90,
            },
            "issues": [],
        }
    )


class WorkflowGroundingFixture:
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        storage = NovelProjectStorage(
            str(Path(self.temp.name) / "novels.db")
        )
        self.service = NovelProjectService(storage)
        self.grounding = ChapterWorkflowGroundingService(self.service)

        self.project = self.service.create_project(
            NovelProjectCreate(
                user_id="workflow-user",
                title="回声港",
                genre="科幻悬疑",
                premise="归航者发现自己的历史被港口系统删除。",
                constraints=["死者不得无解释复活。"],
                style_guide={"pov": "第三人称限知"},
            )
        )
        for entity_id, entity_type, name in (
            ("char_lan", "character", "岚"),
            ("char_qi", "character", "祁"),
            ("loc_gate", "location", "回声门"),
        ):
            self.service.create_entity(
                self.project.novel_id,
                NovelEntityCreate(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    canonical_name=name,
                ),
            )

        bible = self.service.get_story_bible(self.project.novel_id)
        self.bible = self.service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                world={"harbor": "港口会审查每位归航者的身份。"},
                characters=[
                    {"entity_id": "char_lan", "name": "岚"},
                    {"entity_id": "char_qi", "name": "祁"},
                ],
                locations=[
                    {"entity_id": "loc_gate", "name": "回声门"}
                ],
                rules=[{"rule": "身份记录不能由个人直接修改。"}],
                themes=["身份", "记忆"],
            ),
        )
        current_plan = self.service.get_novel_plan(self.project.novel_id)
        self.plan = self.service.update_novel_plan(
            self.project.novel_id,
            NovelPlanUpdate(
                expected_revision=current_plan.revision,
                story_premise="岚追查被删除的归航历史。",
                core_conflict="亲历事实与官方记录冲突。",
                central_question="谁有权定义真实？",
                volume_plans=[
                    {
                        "volume_number": 1,
                        "title": "不存在的归航者",
                        "purpose": "揭开第一层历史篡改。",
                    }
                ],
            ),
        )
        self.arc = self.service.create_story_arc(
            self.project.novel_id,
            StoryArcCreate(
                volume_number=1,
                arc_number=1,
                title="归航审查",
                objective="让岚确认数据库否认整支舰队。",
                core_conflict="个人记忆与公共档案冲突。",
                character_progression=[
                    {
                        "character_id": "char_lan",
                        "character_name": "岚",
                        "start_state": "相信审查只是手续。",
                        "end_state": "开始怀疑制度本身。",
                    }
                ],
            ),
        )
        self.previous = self._create_chapter(1, "抵达")
        self.selected = self._create_chapter(2, "身份不存在")
        self.following = self._create_chapter(3, "秘密证人")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_chapter(self, number: int, title: str):
        return self.service.create_chapter_plan(
            self.project.novel_id,
            ChapterPlanCreate(
                arc_id=self.arc.arc_id,
                chapter_number=number,
                title=title,
                objective=f"推进第 {number} 章的身份冲突。",
                summary=f"第 {number} 章摘要。",
                pov_character_id="char_lan",
                pov_character_name="岚",
                opening_state="岚仍相信自己的记忆。",
                closing_state="岚获得新的矛盾证据。",
                conflict="守门系统拒绝承认岚的身份。",
                reveal="系统中不存在舰队记录。",
                hook="祁暗示有人主动删除了记录。",
                scene_beats=[
                    {
                        "beat_id": f"beat-{number}-1",
                        "order": 1,
                        "title": "接受审查",
                        "summary": "岚与祁在回声门提交身份。",
                        "purpose": "建立制度压力。",
                        "character_ids": ["char_lan", "char_qi"],
                        "location_id": "loc_gate",
                    }
                ],
                continuity_dependencies=[f"chapter-{number - 1}"],
                target_word_count=3200,
            ),
        )

    def request(self, **updates) -> ChapterWorkflowRequest:
        payload = {
            "user_id": "workflow-user",
            "novel_id": self.project.novel_id,
            "instruction": "按已接受的章节规划写出完整正文。",
            "chapter_plan_id": self.selected.chapter_plan_id,
            "chapter_plan_revision": self.selected.revision,
            "use_memory": False,
            "auto_rewrite": False,
        }
        payload.update(updates)
        return ChapterWorkflowRequest(**payload)


class WorkflowGroundingTests(
    WorkflowGroundingFixture,
    unittest.TestCase,
):
    def test_resolve_builds_bounded_targeted_context(self) -> None:
        grounded = self.grounding.resolve(self.request())

        self.assertLessEqual(
            len(grounded.message),
            self.grounding.CONTEXT_CHAR_BUDGET,
        )
        payload = json.loads(grounded.message[grounded.message.index("{") :])
        self.assertEqual(
            payload["binding"]["chapter_plan_id"],
            self.selected.chapter_plan_id,
        )
        self.assertEqual(
            payload["chapter_plan"]["scene_beats"][0]["beat_id"],
            "beat-2-1",
        )
        self.assertIn("conflict", payload["chapter_plan"])
        self.assertIn("reveal", payload["chapter_plan"])
        self.assertIn("hook", payload["chapter_plan"])
        self.assertIn("character_progression", payload["story_arc"])
        self.assertEqual(
            grounded.metadata["active_character_ids"],
            ["char_lan", "char_qi"],
        )
        self.assertEqual(
            grounded.metadata["active_location_ids"],
            ["loc_gate"],
        )
        self.assertEqual(
            grounded.metadata["adjacent_chapter_plan_ids"],
            [
                self.previous.chapter_plan_id,
                self.following.chapter_plan_id,
            ],
        )

    def test_revision_conflict_blocks_before_generation(self) -> None:
        updated = self.service.update_chapter_plan(
            self.project.novel_id,
            self.selected.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=self.selected.revision,
                objective="更新后的章节目标。",
            ),
        )
        self.assertEqual(updated.revision, self.selected.revision + 1)

        with self.assertRaises(ChapterWorkflowGroundingConflictError):
            self.grounding.resolve(self.request())

    def test_stale_chapter_plan_blocks_before_generation(self) -> None:
        self.service.update_project(
            self.project.novel_id,
            NovelProjectUpdate(
                expected_revision=self.project.revision,
                premise="正式设定已经变化。",
            ),
        )

        with self.assertRaisesRegex(
            ChapterWorkflowGroundingConflictError,
            "stale",
        ):
            self.grounding.resolve(self.request())

    def test_context_budget_survives_huge_authoritative_sources(self) -> None:
        project = self.service.update_project(
            self.project.novel_id,
            NovelProjectUpdate(
                expected_revision=self.project.revision,
                premise="设" * 8000,
                constraints=["约束" * 2000 for _ in range(20)],
                style_guide={
                    f"style-{index}": "风格" * 2000
                    for index in range(20)
                },
            ),
        )
        bible = self.service.get_story_bible(self.project.novel_id)
        bible = self.service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                world={
                    f"world-{index}": "世界" * 2000
                    for index in range(20)
                },
                rules=[
                    {"rule": "规则" * 2000}
                    for _ in range(20)
                ],
            ),
        )
        plan = self.service.update_novel_plan(
            self.project.novel_id,
            NovelPlanUpdate(
                expected_revision=self.plan.revision,
                story_premise="主线" * 3000,
                core_conflict="冲突" * 3000,
            ),
        )
        arc = self.service.update_story_arc(
            self.project.novel_id,
            self.arc.arc_id,
            StoryArcUpdate(
                expected_revision=self.arc.revision,
                objective="故事弧目标" * 1000,
                summary="故事弧摘要" * 1000,
            ),
        )
        chapter = self.service.update_chapter_plan(
            self.project.novel_id,
            self.selected.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=self.selected.revision,
                objective="章节目标" * 1000,
                summary="章节摘要" * 1000,
            ),
        )

        grounded = self.grounding.resolve(
            self.request(chapter_plan_revision=chapter.revision)
        )
        payload = json.loads(grounded.message[grounded.message.index("{") :])

        self.assertEqual(project.revision, 2)
        self.assertGreater(bible.revision, self.bible.revision)
        self.assertEqual(plan.revision, self.plan.revision + 1)
        self.assertEqual(arc.revision, self.arc.revision + 1)
        self.assertLessEqual(
            len(grounded.message),
            self.grounding.CONTEXT_CHAR_BUDGET,
        )
        self.assertEqual(
            payload["binding"]["chapter_plan_revision"],
            chapter.revision,
        )
        self.assertIn("chapter_plan", payload)


class WorkflowGroundedExecutionTests(
    WorkflowGroundingFixture,
    unittest.IsolatedAsyncioTestCase,
):
    async def test_all_workflow_stages_receive_grounded_context(self) -> None:
        manager = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    agent_result("chapter", "Draft chapter."),
                    agent_result("review", approved_review()),
                ]
            )
        )
        result = await ChapterWorkflow(
            manager,
            grounding_service=self.grounding,
        ).run(self.request())

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.metadata["grounding_mode"], "chapter_plan")
        self.assertTrue(result.metadata["planning_freshness_validated"])
        self.assertEqual(manager.execute.await_count, 2)
        for call in manager.execute.await_args_list:
            context = call.kwargs["context"]
            self.assertEqual(context.task_mode, "grounded")
            self.assertEqual(
                context.metadata["chapter_plan_id"],
                self.selected.chapter_plan_id,
            )
            self.assertEqual(
                context.messages[0].metadata["source"],
                "chapter_plan_grounding",
            )

    async def test_plan_grounding_precedes_memory_in_agent_prompt(self) -> None:
        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="chapter",
                    provider="qwen_local",
                    model="qwen3:8b",
                )
            )
        )
        agent = NovelAgent(llm_manager)
        context = AgentContext(
            user_id="workflow-user",
            novel_id=self.project.novel_id,
            instruction="写正文",
            messages=[
                ChatMessage(
                    role="system",
                    content="[PLAN]",
                    metadata={
                        "source": "chapter_plan_grounding",
                        "priority": "P0.3",
                    },
                )
            ],
        )

        with patch(
            "app.agents.novel_agent.canon_context_builder.build",
            new=AsyncMock(return_value="[CANON]"),
        ), patch(
            "app.agents.novel_agent.memory_context_builder.build",
            new=AsyncMock(return_value="[MEMORY]"),
        ):
            await agent.run(context)

        request = llm_manager.chat.await_args.args[1]
        sources = [
            item.metadata.get("source")
            for item in request.messages
            if item.role == "system"
        ]
        self.assertLess(
            sources.index("canonical_entity_registry"),
            sources.index("chapter_plan_grounding"),
        )
        self.assertLess(
            sources.index("chapter_plan_grounding"),
            sources.index("long_term_memory"),
        )

    async def test_consistency_constraints_precede_memory_in_agent_prompt(
        self,
    ) -> None:
        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="chapter",
                    provider="qwen_local",
                    model="qwen3:8b",
                )
            )
        )
        agent = NovelAgent(llm_manager)
        context = AgentContext(
            user_id="workflow-user",
            novel_id=self.project.novel_id,
            instruction="写正文",
            messages=[
                ChatMessage(
                    role="system",
                    content="[PLAN]",
                    metadata={
                        "source": "chapter_plan_grounding",
                        "priority": "P0.3",
                    },
                ),
                ChatMessage(
                    role="system",
                    content="[CONSISTENCY]",
                    metadata={
                        "source": "consistency_constraints",
                        "priority": "P0.4",
                    },
                ),
            ],
        )

        with patch(
            "app.agents.novel_agent.canon_context_builder.build",
            new=AsyncMock(return_value="[CANON]"),
        ), patch(
            "app.agents.novel_agent.memory_context_builder.build",
            new=AsyncMock(return_value="[MEMORY]"),
        ):
            await agent.run(context)

        request = llm_manager.chat.await_args.args[1]
        sources = [
            item.metadata.get("source")
            for item in request.messages
            if item.role == "system"
        ]
        self.assertLess(
            sources.index("chapter_plan_grounding"),
            sources.index("consistency_constraints"),
        )
        self.assertLess(
            sources.index("consistency_constraints"),
            sources.index("long_term_memory"),
        )

    async def test_persisted_run_records_plan_binding_and_grounding(self) -> None:
        manager = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    agent_result("chapter", "Draft chapter."),
                    agent_result("review", approved_review()),
                ]
            )
        )
        storage = WorkflowRunStorage(
            str(Path(self.temp.name) / "workflow-runs.db")
        )
        detail = await WorkflowRunService(
            manager,
            storage,
            grounding_service=self.grounding,
        ).start(self.request())

        self.assertEqual(
            detail.request.chapter_plan_id,
            self.selected.chapter_plan_id,
        )
        self.assertEqual(
            detail.request.chapter_plan_revision,
            self.selected.revision,
        )
        self.assertEqual(
            detail.result.metadata["grounding_mode"],
            "chapter_plan",
        )
        reopened = WorkflowRunService(
            manager,
            WorkflowRunStorage(
                str(Path(self.temp.name) / "workflow-runs.db")
            ),
            grounding_service=self.grounding,
        ).get(detail.run_id)
        self.assertEqual(
            reopened.request.chapter_plan_id,
            self.selected.chapter_plan_id,
        )

    async def test_async_worker_revalidates_and_persists_grounding(self) -> None:
        manager = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    agent_result("chapter", "Draft chapter."),
                    agent_result("review", approved_review()),
                ]
            )
        )
        executor = AsyncWorkflowExecutor(
            manager,
            execution_mode="embedded",
            db_path=str(Path(self.temp.name) / "workflow-queue.db"),
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.05,
            grounding_service=self.grounding,
        )
        try:
            submitted = await executor.submit(self.request())
            finished = await executor.wait_for_terminal(
                submitted.run.run_id
            )
        finally:
            await executor.shutdown()

        self.assertEqual(finished.job.queue_status, "completed")
        self.assertEqual(finished.run.execution_status, "succeeded")
        self.assertEqual(
            finished.run.request.chapter_plan_id,
            self.selected.chapter_plan_id,
        )
        self.assertEqual(
            finished.run.result.metadata["grounding_mode"],
            "chapter_plan",
        )

    async def test_async_worker_rejects_plan_that_stales_in_queue(self) -> None:
        manager = SimpleNamespace(execute=AsyncMock())
        queue_path = str(Path(self.temp.name) / "workflow-race.db")
        submitter = AsyncWorkflowExecutor(
            manager,
            execution_mode="external",
            db_path=queue_path,
            poll_interval=0.01,
            grounding_service=self.grounding,
        )
        submitted = await submitter.submit(
            self.request(),
            max_attempts=1,
        )
        self.service.update_project(
            self.project.novel_id,
            NovelProjectUpdate(
                expected_revision=self.project.revision,
                genre="设定已变化",
            ),
        )
        worker = AsyncWorkflowExecutor(
            manager,
            execution_mode="worker",
            db_path=queue_path,
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.05,
            grounding_service=self.grounding,
        )
        worker.ensure_started()
        try:
            finished = await worker.wait_for_terminal(
                submitted.run.run_id,
                timeout=5.0,
            )
        finally:
            await worker.shutdown()
            await submitter.shutdown()

        self.assertEqual(finished.job.queue_status, "dead_letter")
        self.assertEqual(finished.run.execution_status, "dead_letter")
        self.assertIn("stale", finished.run.error)
        manager.execute.assert_not_awaited()


class WorkflowGroundingApiTests(
    WorkflowGroundingFixture,
    unittest.TestCase,
):
    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        from app.api.v1 import workflows

        self.module = workflows
        self.original_grounding = workflows.chapter_workflow_grounding_service
        self.original_agent_manager = workflows._agent_manager
        workflows.chapter_workflow_grounding_service = self.grounding
        self.manager = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    agent_result("chapter", "Draft chapter."),
                    agent_result("review", approved_review()),
                ]
            )
        )
        workflows._agent_manager = lambda request: self.manager
        app = FastAPI()
        app.include_router(workflows.router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.module.chapter_workflow_grounding_service = (
            self.original_grounding
        )
        self.module._agent_manager = self.original_agent_manager
        super().tearDown()

    def test_new_http_workflow_requires_explicit_plan_binding(self) -> None:
        response = self.client.post(
            "/api/v1/workflows/chapter",
            json={
                "user_id": "workflow-user",
                "novel_id": self.project.novel_id,
                "instruction": "写正文",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("chapter_plan_id", response.json()["detail"])

    def test_http_workflow_maps_revision_conflict_to_409(self) -> None:
        response = self.client.post(
            "/api/v1/workflows/chapter",
            json=self.request(
                chapter_plan_revision=999,
            ).model_dump(mode="json"),
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("revision conflict", response.json()["detail"])
        self.manager.execute.assert_not_awaited()

    def test_http_workflow_maps_missing_plan_to_404(self) -> None:
        response = self.client.post(
            "/api/v1/workflows/chapter",
            json=self.request(
                chapter_plan_id="missing-plan",
            ).model_dump(mode="json"),
        )
        self.assertEqual(response.status_code, 404)
        self.manager.execute.assert_not_awaited()

    def test_valid_http_workflow_returns_grounding_metadata(self) -> None:
        response = self.client.post(
            "/api/v1/workflows/chapter",
            json=self.request().model_dump(mode="json"),
        )
        self.assertEqual(response.status_code, 200)
        metadata = response.json()["data"]["metadata"]
        self.assertEqual(metadata["grounding_mode"], "chapter_plan")
        self.assertEqual(
            metadata["chapter_plan_id"],
            self.selected.chapter_plan_id,
        )

    def test_openapi_marks_plan_binding_required(self) -> None:
        schema = self.client.app.openapi()["components"]["schemas"][
            "ChapterWorkflowRequest"
        ]
        self.assertIn("chapter_plan_id", schema["required"])
        self.assertIn("chapter_plan_revision", schema["required"])


if __name__ == "__main__":
    unittest.main()
