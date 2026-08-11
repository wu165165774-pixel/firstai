from __future__ import annotations

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.manuscripts.schemas import ManuscriptAcceptRequest
from app.manuscripts.service import ManuscriptService
from app.manuscripts.storage import ManuscriptStorage
from app.novels.schemas import (
    ChapterPlanCreate,
    NovelPlanUpdate,
    NovelProjectCreate,
    StoryArcCreate,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.orchestrator.schemas import NovelOrchestrationCreateRequest
from app.orchestrator.service import NovelOrchestrationService
from app.orchestrator.storage import (
    NovelOrchestrationConflictError,
    NovelOrchestrationStorage,
)
from app.workflows.async_queue import WorkflowAsyncQueue
from app.workflows.grounding import ChapterWorkflowGroundingService
from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResult,
    ReviewReport,
    ReviewScores,
    WorkflowStep,
)


def review_scores() -> ReviewScores:
    return ReviewScores(
        continuity=92,
        character_consistency=93,
        world_consistency=94,
        plot_logic=91,
        prose_quality=88,
        pacing=90,
        overall=91,
    )


class NovelOrchestratorFixture:
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = self.temp.name
        self.novel_db = root + "/novels.db"
        self.workflow_db = root + "/workflow-runs.db"
        self.novel_service = NovelProjectService(
            NovelProjectStorage(self.novel_db)
        )
        self.project = self.novel_service.create_project(
            NovelProjectCreate(
                user_id="orchestrator-user",
                title="潮汐长卷",
                genre="悬疑",
                premise="档案员追查被删除的舰队。",
            )
        )
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        self.bible = self.novel_service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                world={"harbor": "归航记录由潮汐系统验证。"},
                themes=["身份", "记忆"],
            ),
        )
        current_plan = self.novel_service.get_novel_plan(
            self.project.novel_id
        )
        self.plan = self.novel_service.update_novel_plan(
            self.project.novel_id,
            NovelPlanUpdate(
                expected_revision=current_plan.revision,
                story_premise="岚追查被删除的归航记录。",
                core_conflict="亲历事实与官方档案冲突。",
                volume_plans=[
                    {"volume_number": 1, "title": "不存在的归航者"}
                ],
            ),
        )
        self.arc = self.novel_service.create_story_arc(
            self.project.novel_id,
            StoryArcCreate(
                volume_number=1,
                arc_number=1,
                title="归航审查",
                objective="确认舰队存在。",
                target_chapter_start=1,
                target_chapter_end=3,
            ),
        )
        self.chapters = [
            self._create_chapter(number)
            for number in (1, 2, 3)
        ]
        self.queue = WorkflowAsyncQueue(self.workflow_db)
        self.manuscript_storage = ManuscriptStorage(self.novel_db)
        self.manuscript_service = ManuscriptService(
            self.manuscript_storage,
            self.queue.run_storage,
        )
        self.grounding = ChapterWorkflowGroundingService(
            self.novel_service,
            manuscript_storage=self.manuscript_storage,
        )
        self.storage = NovelOrchestrationStorage(self.workflow_db)
        self.service = NovelOrchestrationService(
            self.storage,
            self.queue,
            self.novel_service,
            self.manuscript_service,
            self.grounding,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_chapter(self, number: int):
        return self.novel_service.create_chapter_plan(
            self.project.novel_id,
            ChapterPlanCreate(
                arc_id=self.arc.arc_id,
                chapter_number=number,
                title=f"潮汐第{number}章",
                objective=f"推进第 {number} 章调查。",
                summary=f"第 {number} 章规划摘要。",
                opening_state="岚仍在追查记录。",
                closing_state="岚获得新证据。",
                conflict="档案系统阻止查询。",
                reveal=f"发现第 {number} 份证据。",
                hook="下一条记录指向更深处。",
                scene_beats=[
                    {
                        "beat_id": f"beat-{number}",
                        "order": 1,
                        "title": "核对记录",
                        "summary": "岚核对纸本和数据库。",
                        "purpose": "推进调查。",
                    }
                ],
                continuity_dependencies=(
                    [f"chapter-{number - 1}"] if number > 1 else []
                ),
                target_word_count=1000,
            ),
        )

    def payload(self, **updates) -> NovelOrchestrationCreateRequest:
        value = {
            "user_id": self.project.user_id,
            "workflow": {
                "instruction_template": (
                    "写第 {chapter_number} 章《{chapter_title}》。"
                ),
                "use_memory": False,
                "auto_rewrite": False,
                "minimum_overall_score": 0,
                "minimum_dimension_score": 0,
                "require_all_issues_resolved": False,
            },
        }
        value.update(updates)
        return NovelOrchestrationCreateRequest.model_validate(value)

    def create(self, **updates):
        return self.service.create(
            self.project.novel_id,
            self.payload(**updates),
        ).orchestration

    def complete_workflow(
        self,
        detail,
        *,
        content: str | None = None,
        approved: bool = True,
    ) -> str:
        step = next(
            item
            for item in detail.steps
            if item.sequence_no == detail.current_sequence_no
        )
        run_id = step.workflow_run_id
        assert run_id is not None
        content = content or f"第 {step.chapter_number} 章正式候选。"
        scores = review_scores()
        report = ReviewReport(
            approved=approved,
            summary="审核通过。" if approved else "需要继续修改。",
            scores=scores,
            issues=[],
        )
        result = ChapterWorkflowResult(
            status="completed" if approved else "max_revisions_reached",
            draft=content,
            review_report=report,
            review_history=[report],
            final_content=content,
            quality_scores=scores,
            quality_score_history=[scores],
            quality_gate_passed=approved,
            workflow_steps=[
                WorkflowStep(
                    stage="draft",
                    round_index=0,
                    attempt_index=1,
                    agent="chapter",
                    success=True,
                    content=content,
                    provider="test",
                    model="test-model",
                    finish_reason="stop",
                )
            ],
            metadata={
                "grounding_mode": "chapter_plan",
                "planning_freshness_validated": True,
                "chapter_plan_id": step.chapter_plan_id,
                "chapter_plan_revision": step.chapter_plan_revision,
                "chapter_number": step.chapter_number,
                "story_arc_id": step.arc_id,
                "story_arc_revision": step.arc_revision,
                "novel_plan_revision": self.plan.revision,
                "source_project_revision": self.project.revision,
                "source_story_bible_revision": self.bible.revision,
            },
        )
        self.queue.run_storage.finalize_run(run_id, result)
        self.queue.mark_terminal(run_id)
        return run_id

    def import_candidate(self, detail):
        return self.service.advance(
            self.project.novel_id,
            detail.orchestration_id,
            expected_revision=detail.revision,
        )

    def accept_candidate(self, detail):
        step = next(
            item
            for item in detail.steps
            if item.sequence_no == detail.current_sequence_no
        )
        manuscript = self.manuscript_service.get_chapter(
            self.project.novel_id,
            str(step.manuscript_chapter_id),
        )
        return self.manuscript_service.accept_revision(
            self.project.novel_id,
            str(step.manuscript_chapter_id),
            int(step.candidate_revision),
            ManuscriptAcceptRequest(
                expected_manuscript_revision=manuscript.chapter.revision
            ),
        )


class NovelOrchestrationStorageTests(
    NovelOrchestratorFixture,
    unittest.TestCase,
):
    def test_schema_contains_state_machine_tables(self) -> None:
        import sqlite3

        with sqlite3.connect(self.workflow_db) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("novel_orchestrations", tables)
        self.assertIn("novel_orchestration_steps", tables)
        self.assertIn("novel_orchestration_events", tables)

    def test_reopen_preserves_orchestration_and_events(self) -> None:
        created = self.create()
        reopened = NovelOrchestrationStorage(self.workflow_db).get(
            self.project.novel_id,
            created.orchestration_id,
        )
        self.assertEqual(reopened.status, "waiting_for_workflow")
        self.assertEqual(reopened.steps[0].workflow_run_id, created.steps[0].workflow_run_id)
        self.assertEqual(
            [event.event_type for event in reopened.events[:2]],
            ["orchestration_created", "chapter_workflow_queued"],
        )


class NovelOrchestrationServiceTests(
    NovelOrchestratorFixture,
    unittest.TestCase,
):
    def test_create_snapshots_order_and_enqueues_only_first(self) -> None:
        created = self.create()
        self.assertEqual(created.status, "waiting_for_workflow")
        self.assertEqual(created.revision, 2)
        self.assertEqual(
            [step.chapter_number for step in created.steps],
            [1, 2, 3],
        )
        self.assertIsNotNone(created.steps[0].workflow_run_id)
        self.assertIsNone(created.steps[1].workflow_run_id)
        run = self.queue.run_storage.get_run(created.steps[0].workflow_run_id)
        self.assertEqual(
            run["request"]["chapter_plan_id"],
            self.chapters[0].chapter_plan_id,
        )
        self.assertIn("潮汐第1章", run["request"]["instruction"])

    def test_create_filters_range_and_is_idempotent(self) -> None:
        payload = self.payload(start_chapter_number=2, end_chapter_number=3)
        first = self.service.create(
            self.project.novel_id,
            payload,
            idempotency_key="orchestration-key",
        )
        second = self.service.create(
            self.project.novel_id,
            payload,
            idempotency_key="orchestration-key",
        )
        self.assertFalse(first.deduplicated)
        self.assertTrue(second.deduplicated)
        self.assertEqual(
            second.orchestration.orchestration_id,
            first.orchestration.orchestration_id,
        )
        self.assertEqual(
            [item.chapter_number for item in first.orchestration.steps],
            [2, 3],
        )

    def test_create_rejects_wrong_owner_and_stale_plan(self) -> None:
        with self.assertRaisesRegex(
            NovelOrchestrationConflictError,
            "does not own",
        ):
            self.service.create(
                self.project.novel_id,
                self.payload(user_id="other-user"),
            )
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        self.novel_service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                themes=["新的主题"],
            ),
        )
        with self.assertRaisesRegex(
            NovelOrchestrationConflictError,
            "Novel Plan is stale",
        ):
            self.create()

    def test_advance_is_idempotent_while_workflow_is_active(self) -> None:
        created = self.create()
        advanced = self.service.advance(
            self.project.novel_id,
            created.orchestration_id,
            expected_revision=created.revision,
        )
        self.assertEqual(advanced.revision, created.revision)
        self.assertEqual(advanced.status, "waiting_for_workflow")

    def test_success_imports_candidate_without_accepting_or_advancing(self) -> None:
        created = self.create()
        self.complete_workflow(created)
        candidate = self.import_candidate(created)
        self.assertEqual(candidate.status, "waiting_for_acceptance")
        self.assertEqual(candidate.current_sequence_no, 1)
        self.assertIsNotNone(candidate.steps[0].candidate_revision)
        self.assertIsNone(candidate.steps[0].accepted_revision)
        self.assertIsNone(candidate.steps[1].workflow_run_id)
        manuscript = self.manuscript_service.get_chapter(
            self.project.novel_id,
            candidate.steps[0].manuscript_chapter_id,
        )
        self.assertIsNone(manuscript.chapter.accepted_revision)

    def test_explicit_acceptance_enqueues_next_with_continuity(self) -> None:
        created = self.create()
        self.complete_workflow(created, content="第一章已接受连续性标记。")
        candidate = self.import_candidate(created)
        accepted = self.accept_candidate(candidate)
        self.assertEqual(accepted.chapter.accepted_revision, 1)

        next_detail = self.service.advance(
            self.project.novel_id,
            candidate.orchestration_id,
            expected_revision=candidate.revision,
        )
        self.assertEqual(next_detail.status, "waiting_for_workflow")
        self.assertEqual(next_detail.current_sequence_no, 2)
        self.assertEqual(next_detail.accepted_chapters, 1)
        self.assertIsNotNone(next_detail.steps[1].workflow_run_id)
        request = self.queue.run_storage.get_run(
            next_detail.steps[1].workflow_run_id
        )["request"]
        grounding = self.grounding.resolve(
            ChapterWorkflowRequest.model_validate(request)
        )
        self.assertEqual(
            grounding.metadata["accepted_manuscript_chapter_ids"],
            [accepted.chapter.manuscript_chapter_id],
        )

    def test_pause_does_not_cancel_inflight_and_resume_reconciles(self) -> None:
        created = self.create()
        paused = self.service.pause(
            self.project.novel_id,
            created.orchestration_id,
            expected_revision=created.revision,
        )
        self.assertEqual(paused.status, "paused")
        self.assertEqual(
            self.queue.get_control(created.steps[0].workflow_run_id)[
                "queue_status"
            ],
            "queued",
        )
        self.complete_workflow(created)
        unchanged = self.service.advance(
            self.project.novel_id,
            paused.orchestration_id,
            expected_revision=paused.revision,
        )
        self.assertEqual(unchanged.status, "paused")
        resumed = self.service.resume(
            self.project.novel_id,
            paused.orchestration_id,
            expected_revision=paused.revision,
        )
        self.assertEqual(resumed.status, "waiting_for_acceptance")

    def test_failed_queue_run_can_retry_same_run(self) -> None:
        created = self.create()
        run_id = created.steps[0].workflow_run_id
        self.queue.run_storage.fail_run(run_id, "temporary failure")
        self.queue.mark_failed(run_id)
        failed = self.import_candidate(created)
        self.assertEqual(failed.status, "failed")
        self.assertIn("temporary failure", failed.error)
        retried = self.service.retry(
            self.project.novel_id,
            failed.orchestration_id,
            expected_revision=failed.revision,
        )
        self.assertEqual(retried.status, "waiting_for_workflow")
        self.assertEqual(retried.steps[0].workflow_run_id, run_id)
        self.assertEqual(self.queue.get_control(run_id)["queue_status"], "queued")

    def test_quality_gate_failure_retries_with_new_run(self) -> None:
        created = self.create()
        old_run = self.complete_workflow(created, approved=False)
        failed = self.import_candidate(created)
        self.assertEqual(failed.status, "failed")
        retried = self.service.retry(
            self.project.novel_id,
            failed.orchestration_id,
            expected_revision=failed.revision,
        )
        self.assertNotEqual(retried.steps[0].workflow_run_id, old_run)
        self.assertEqual(retried.steps[0].workflow_attempt, 2)

    def test_human_can_retry_without_accepting_candidate(self) -> None:
        created = self.create()
        old_run = self.complete_workflow(created)
        candidate = self.import_candidate(created)
        retried = self.service.retry(
            self.project.novel_id,
            candidate.orchestration_id,
            expected_revision=candidate.revision,
        )
        self.assertEqual(retried.status, "waiting_for_workflow")
        self.assertNotEqual(retried.steps[0].workflow_run_id, old_run)
        self.assertIsNone(retried.steps[0].candidate_revision)
        previous = self.manuscript_service.list_chapters(
            self.project.novel_id
        )[0]
        self.assertIsNone(previous.accepted_revision)

    def test_preaccepted_chapter_is_skipped(self) -> None:
        first = self.create(start_chapter_number=1, end_chapter_number=1)
        self.complete_workflow(first)
        candidate = self.import_candidate(first)
        self.accept_candidate(candidate)

        created = self.create()
        self.assertEqual(created.accepted_chapters, 1)
        self.assertEqual(created.current_sequence_no, 2)
        self.assertEqual(created.steps[0].status, "accepted")
        self.assertIsNotNone(created.steps[1].workflow_run_id)

    def test_two_chapters_complete_only_after_both_acceptances(self) -> None:
        detail = self.create(end_chapter_number=2)
        for expected_sequence in (1, 2):
            self.complete_workflow(detail)
            candidate = self.import_candidate(detail)
            self.accept_candidate(candidate)
            detail = self.service.advance(
                self.project.novel_id,
                candidate.orchestration_id,
                expected_revision=candidate.revision,
            )
            if expected_sequence == 1:
                self.assertEqual(detail.current_sequence_no, 2)
        self.assertEqual(detail.status, "completed")
        self.assertEqual(detail.accepted_chapters, 2)
        self.assertIsNone(detail.current_sequence_no)

    def test_revision_conflict_is_rejected(self) -> None:
        created = self.create()
        with self.assertRaisesRegex(
            NovelOrchestrationConflictError,
            "revision conflict",
        ):
            self.service.pause(
                self.project.novel_id,
                created.orchestration_id,
                expected_revision=99,
            )

    def test_stale_next_chapter_fails_before_enqueue(self) -> None:
        detail = self.create(end_chapter_number=2)
        self.complete_workflow(detail)
        candidate = self.import_candidate(detail)
        self.accept_candidate(candidate)
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        self.novel_service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                themes=["规划已变化"],
            ),
        )
        with self.assertRaisesRegex(
            NovelOrchestrationConflictError,
            "Novel Plan is stale",
        ):
            self.service.advance(
                self.project.novel_id,
                candidate.orchestration_id,
                expected_revision=candidate.revision,
            )
        persisted = self.service.get(
            self.project.novel_id,
            candidate.orchestration_id,
        )
        self.assertEqual(persisted.status, "failed")
        self.assertIsNone(persisted.steps[1].workflow_run_id)


class NovelOrchestrationApiTests(
    NovelOrchestratorFixture,
    unittest.TestCase,
):
    def setUp(self) -> None:
        super().setUp()
        from app.api.v1 import orchestrations

        self.module = orchestrations
        self.original_service = orchestrations.service
        self.original_ensure = orchestrations._ensure_worker
        orchestrations.service = self.service
        orchestrations._ensure_worker = lambda request: None
        app = FastAPI()
        app.include_router(orchestrations.router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.module.service = self.original_service
        self.module._ensure_worker = self.original_ensure
        super().tearDown()

    def test_create_list_get_pause_resume_api(self) -> None:
        created = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}/orchestrations",
            headers={"Idempotency-Key": "api-orchestration"},
            json=self.payload().model_dump(mode="json"),
        )
        self.assertEqual(created.status_code, 201)
        detail = created.json()["data"]["orchestration"]
        orchestration_id = detail["orchestration_id"]

        listed = self.client.get(
            f"/api/v1/novels/{self.project.novel_id}/orchestrations"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["data"]), 1)

        fetched = self.client.get(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/orchestrations/{orchestration_id}"
        )
        self.assertEqual(fetched.status_code, 200)

        paused = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/orchestrations/{orchestration_id}/pause",
            json={"expected_revision": detail["revision"]},
        )
        self.assertEqual(paused.status_code, 200)
        paused_revision = paused.json()["data"]["revision"]
        resumed = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/orchestrations/{orchestration_id}/resume",
            json={"expected_revision": paused_revision},
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(
            resumed.json()["data"]["status"],
            "waiting_for_workflow",
        )

    def test_api_maps_not_found_and_conflict(self) -> None:
        missing = self.client.get(
            f"/api/v1/novels/{self.project.novel_id}"
            "/orchestrations/missing"
        )
        self.assertEqual(missing.status_code, 404)
        created = self.create()
        conflict = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/orchestrations/{created.orchestration_id}/pause",
            json={"expected_revision": 99},
        )
        self.assertEqual(conflict.status_code, 409)

    def test_openapi_registers_orchestration_routes(self) -> None:
        paths = self.client.app.openapi()["paths"]
        prefix = "/api/v1/novels/{novel_id}/orchestrations"
        self.assertIn(prefix, paths)
        self.assertIn(prefix + "/{orchestration_id}/advance", paths)
        self.assertIn(prefix + "/{orchestration_id}/pause", paths)
        self.assertIn(prefix + "/{orchestration_id}/resume", paths)
        self.assertIn(prefix + "/{orchestration_id}/retry", paths)


if __name__ == "__main__":
    unittest.main()
