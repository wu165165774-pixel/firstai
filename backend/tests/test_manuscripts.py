from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.manuscripts.schemas import (
    ManuscriptAcceptRequest,
    ManuscriptImportRequest,
)
from app.manuscripts.service import ManuscriptService
from app.manuscripts.storage import (
    ManuscriptConflictError,
    ManuscriptStorage,
)
from app.novels.schemas import (
    ChapterPlanCreate,
    NovelEntityCreate,
    NovelPlanUpdate,
    NovelProjectCreate,
    StoryArcCreate,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.workflows.grounding import ChapterWorkflowGroundingService
from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResult,
    ReviewReport,
    ReviewScores,
    WorkflowStep,
)
from app.workflows.storage import WorkflowRunStorage


def scores() -> ReviewScores:
    return ReviewScores(
        continuity=92,
        character_consistency=93,
        world_consistency=94,
        plot_logic=91,
        prose_quality=88,
        pacing=90,
        overall=91,
    )


async def _zero_async() -> int:
    return 0


class ManuscriptFixture:
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.novel_db = str(root / "novels.db")
        self.workflow_db = str(root / "workflow-runs.db")
        self.novel_storage = NovelProjectStorage(self.novel_db)
        self.novel_service = NovelProjectService(self.novel_storage)
        self.manuscript_storage = ManuscriptStorage(self.novel_db)
        self.workflow_storage = WorkflowRunStorage(self.workflow_db)
        self.service = ManuscriptService(
            self.manuscript_storage,
            self.workflow_storage,
        )

        self.project = self.novel_service.create_project(
            NovelProjectCreate(
                user_id="manuscript-user",
                title="潮汐档案",
                genre="悬疑",
                premise="档案员发现被删除的潮汐记录。",
            )
        )
        for entity_id, entity_type, name in (
            ("char_lan", "character", "岚"),
            ("char_qi", "character", "祁"),
            ("loc_tower", "location", "北塔"),
        ):
            self.novel_service.create_entity(
                self.project.novel_id,
                NovelEntityCreate(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    canonical_name=name,
                ),
            )
        current_plan = self.novel_service.get_novel_plan(
            self.project.novel_id
        )
        self.plan = self.novel_service.update_novel_plan(
            self.project.novel_id,
            NovelPlanUpdate(
                expected_revision=current_plan.revision,
                story_premise="档案员追查被删除的潮汐记录。",
                core_conflict="亲历事实与港务档案冲突。",
                volume_plans=[
                    {
                        "volume_number": 1,
                        "title": "失落潮位",
                    }
                ],
            ),
        )
        self.arc = self.novel_service.create_story_arc(
            self.project.novel_id,
            StoryArcCreate(
                volume_number=1,
                arc_number=1,
                title="空白潮汐",
                objective="找到第一份删除证据。",
            ),
        )
        self.chapter_one = self._create_chapter(1, "旧堤")
        self.chapter_two = self._create_chapter(2, "回潮")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_chapter(self, number: int, title: str):
        return self.novel_service.create_chapter_plan(
            self.project.novel_id,
            ChapterPlanCreate(
                arc_id=self.arc.arc_id,
                chapter_number=number,
                title=title,
                objective=f"完成第 {number} 章目标。",
                summary=f"第 {number} 章规划摘要。",
                opening_state="主角仍相信正式档案。",
                closing_state="主角得到新的矛盾证据。",
                conflict="旧记录与当前数据库冲突。",
                reveal="潮位数据被人为删除。",
                hook="下一份记录指向封锁区。",
                scene_beats=[
                    {
                        "beat_id": f"beat-{number}",
                        "order": 1,
                        "title": "核对档案",
                        "summary": "主角核对纸本与数据库。",
                        "purpose": "建立证据冲突。",
                    }
                ],
                target_word_count=1200,
            ),
        )

    def create_workflow(
        self,
        *,
        chapter=None,
        contents: list[str] | None = None,
        approved: bool = True,
        novel_id: str | None = None,
        candidate_facts: list[dict] | None = None,
    ) -> str:
        chapter = chapter or self.chapter_one
        contents = contents or ["第一版正文。", "修订后的正文。"]
        request = ChapterWorkflowRequest(
            user_id=self.project.user_id,
            novel_id=novel_id or self.project.novel_id,
            instruction="按规划生成正文。",
            chapter_plan_id=chapter.chapter_plan_id,
            chapter_plan_revision=chapter.revision,
            use_memory=False,
            auto_rewrite=False,
        )
        created = self.workflow_storage.create_run(request)
        workflow_steps = [
            WorkflowStep(
                stage="draft" if index == 0 else "rewrite",
                round_index=index,
                attempt_index=1,
                agent="chapter" if index == 0 else "rewrite",
                success=True,
                content=content,
                provider="test",
                model="test-model",
                finish_reason="stop",
            )
            for index, content in enumerate(contents)
        ]
        review_scores = scores()
        report = ReviewReport(
            approved=approved,
            summary="审核通过。" if approved else "仍需修改。",
            scores=review_scores,
            issues=[],
            candidate_facts=candidate_facts or [],
        )
        result = ChapterWorkflowResult(
            status="completed" if approved else "max_revisions_reached",
            draft=contents[0],
            review_report=report,
            review_history=[report],
            final_content=contents[-1],
            quality_scores=review_scores,
            quality_score_history=[review_scores],
            quality_gate_passed=approved,
            workflow_steps=workflow_steps,
            metadata={
                "grounding_mode": "chapter_plan",
                "planning_freshness_validated": True,
                "chapter_plan_id": chapter.chapter_plan_id,
                "chapter_plan_revision": chapter.revision,
                "chapter_number": chapter.chapter_number,
                "story_arc_id": self.arc.arc_id,
                "story_arc_revision": self.arc.revision,
                "novel_plan_revision": self.plan.revision,
                "source_project_revision": self.project.revision,
                "source_story_bible_revision": (
                    self.novel_service.get_story_bible(
                        self.project.novel_id
                    ).revision
                ),
            },
        )
        self.workflow_storage.finalize_run(created["run_id"], result)
        return created["run_id"]

    def import_run(
        self,
        run_id: str,
        *,
        expected: int | None = None,
    ):
        return self.service.import_workflow_candidate(
            self.project.novel_id,
            ManuscriptImportRequest(
                workflow_run_id=run_id,
                expected_manuscript_revision=expected,
            ),
        )


class ManuscriptStorageTests(ManuscriptFixture, unittest.TestCase):
    def test_schema_contains_manuscript_tables(self) -> None:
        with sqlite3.connect(self.novel_db) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        self.assertIn("manuscript_chapters", tables)
        self.assertIn("manuscript_revisions", tables)
        self.assertIn("manuscript_fact_projections", tables)
        self.assertIn("idx_manuscript_chapters_order", indexes)
        self.assertIn("idx_manuscript_revisions_time", indexes)
        self.assertIn("idx_fact_projections_status", indexes)
        self.assertIn("idx_fact_projections_revision", indexes)
        self.assertIn("idx_fact_projections_replacement", indexes)

    def test_import_creates_stable_chapter_and_immutable_revisions(self) -> None:
        run_id = self.create_workflow()
        imported = self.import_run(run_id)

        self.assertFalse(imported.deduplicated)
        self.assertEqual(imported.chapter.chapter_number, 1)
        self.assertEqual(imported.chapter.revision, 1)
        self.assertEqual(imported.chapter.latest_revision, 2)
        self.assertIsNone(imported.chapter.accepted_revision)
        self.assertEqual(
            [item.source_stage for item in imported.imported_revisions],
            ["draft", "rewrite"],
        )
        self.assertEqual(
            [item.review_status for item in imported.imported_revisions],
            ["superseded", "approved"],
        )
        approved = imported.imported_revisions[-1]
        self.assertEqual(approved.source_workflow_run_id, run_id)
        self.assertEqual(
            approved.source_chapter_plan_id,
            self.chapter_one.chapter_plan_id,
        )
        self.assertEqual(approved.source_novel_plan_revision, 2)
        self.assertEqual(approved.quality_scores["overall"], 91.0)

    def test_only_approved_revision_freezes_candidate_facts(self) -> None:
        fact = {
            "fact_id": "FACT-001",
            "fact_type": "event",
            "subject_name": "档案员",
            "predicate": "发现",
            "evidence": "档案员发现被删除的记录。",
            "chapter_number": 1,
        }
        imported = self.import_run(
            self.create_workflow(
                contents=["草稿。", "档案员发现被删除的记录。"],
                candidate_facts=[fact],
            )
        )

        self.assertEqual(imported.imported_revisions[0].candidate_facts, [])
        self.assertEqual(
            imported.imported_revisions[1].candidate_facts[0].fact_id,
            "FACT-001",
        )

    def test_import_rejects_persisted_blocking_consistency_conflict(self) -> None:
        run_id = self.create_workflow(contents=["仍有冲突的正文。"])
        with self.workflow_storage._connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            import json

            result = json.loads(row["result_json"])
            result["consistency_conflicts"] = [
                {
                    "conflict_id": "CONFLICT-1",
                    "conflict_type": "relationship_conflict",
                    "severity": "major",
                    "status": "confirmed",
                    "blocking": True,
                    "message": "conflict",
                    "expected": "ally",
                    "generated": "enemy",
                    "recommendation": "rewrite",
                    "entity_ids": [],
                    "candidate_fact_id": "FACT-1",
                    "evidence": [],
                }
            ]
            conn.execute(
                "UPDATE workflow_runs SET result_json = ? WHERE run_id = ?",
                (json.dumps(result, ensure_ascii=False), run_id),
            )
            conn.commit()

        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "unresolved blocking consistency conflicts",
        ):
            self.import_run(run_id)

    def test_import_rejects_candidate_fact_wrong_chapter(self) -> None:
        run_id = self.create_workflow(
            contents=["档案员发现记录。"],
            candidate_facts=[
                {
                    "fact_id": "FACT-WRONG-CHAPTER",
                    "fact_type": "event",
                    "subject_name": "档案员",
                    "predicate": "发现",
                    "evidence": "档案员发现记录。",
                    "chapter_number": 2,
                }
            ],
        )

        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "candidate fact chapter",
        ):
            self.import_run(run_id)

    def test_import_is_idempotent_by_workflow_run(self) -> None:
        run_id = self.create_workflow()
        first = self.import_run(run_id)
        second = self.import_run(run_id)

        self.assertTrue(second.deduplicated)
        self.assertEqual(
            second.chapter.manuscript_chapter_id,
            first.chapter.manuscript_chapter_id,
        )
        self.assertEqual(second.chapter.latest_revision, 2)
        self.assertEqual(len(second.imported_revisions), 2)

    def test_unapproved_workflow_cannot_be_imported(self) -> None:
        run_id = self.create_workflow(approved=False)
        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "quality-gate-passed",
        ):
            self.import_run(run_id)

    def test_workflow_from_different_novel_cannot_be_imported(self) -> None:
        run_id = self.create_workflow(
            contents=["其他小说正文。"],
            novel_id="different-novel",
        )
        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "different Novel Project",
        ):
            self.import_run(run_id)

    def test_existing_chapter_requires_optimistic_concurrency(self) -> None:
        first_run = self.create_workflow(contents=["第一候选。"])
        first = self.import_run(first_run)
        second_run = self.create_workflow(contents=["第二候选。"])

        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "expected_manuscript_revision is required",
        ):
            self.import_run(second_run)
        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "revision conflict",
        ):
            self.import_run(second_run, expected=99)

        second = self.import_run(
            second_run,
            expected=first.chapter.revision,
        )
        self.assertEqual(
            second.chapter.manuscript_chapter_id,
            first.chapter.manuscript_chapter_id,
        )
        self.assertEqual(second.chapter.revision, 2)
        self.assertEqual(second.chapter.latest_revision, 2)

    def test_accept_promotes_only_approved_revision(self) -> None:
        imported = self.import_run(self.create_workflow())
        chapter_id = imported.chapter.manuscript_chapter_id

        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "approved reviewed candidate",
        ):
            self.service.accept_revision(
                self.project.novel_id,
                chapter_id,
                1,
                ManuscriptAcceptRequest(
                    expected_manuscript_revision=1
                ),
            )

        accepted = self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            2,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        self.assertTrue(accepted.changed)
        self.assertEqual(accepted.chapter.revision, 2)
        self.assertEqual(accepted.chapter.accepted_revision, 2)
        self.assertTrue(accepted.accepted_revision.is_accepted)

        repeated = self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            2,
            ManuscriptAcceptRequest(expected_manuscript_revision=2),
        )
        self.assertFalse(repeated.changed)
        self.assertEqual(repeated.chapter.revision, 2)

    def test_accept_rechecks_source_revisions(self) -> None:
        imported = self.import_run(
            self.create_workflow(contents=["待接受正文。"])
        )
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        self.novel_service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                themes=["变更后的主题"],
            ),
        )
        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "Novel Plan is stale",
        ):
            self.service.accept_revision(
                self.project.novel_id,
                imported.chapter.manuscript_chapter_id,
                1,
                ManuscriptAcceptRequest(
                    expected_manuscript_revision=1
                ),
            )

    def test_import_rejects_stale_workflow_snapshot(self) -> None:
        run_id = self.create_workflow(contents=["旧规划正文。"])
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        self.novel_service.update_story_bible(
            self.project.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                themes=["新主题"],
            ),
        )
        with self.assertRaisesRegex(
            ManuscriptConflictError,
            "Novel Plan is stale",
        ):
            self.import_run(run_id)

    def test_storage_reopen_preserves_accepted_revision(self) -> None:
        imported = self.import_run(
            self.create_workflow(contents=["正式正文。"])
        )
        chapter_id = imported.chapter.manuscript_chapter_id
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )

        reopened = ManuscriptStorage(self.novel_db)
        detail = reopened.get_chapter(self.project.novel_id, chapter_id)
        self.assertEqual(detail.chapter.accepted_revision, 1)
        self.assertEqual(detail.accepted.content, "正式正文。")
        self.assertTrue(detail.accepted.is_accepted)

    def test_grounding_uses_only_accepted_prior_manuscript(self) -> None:
        imported = self.import_run(
            self.create_workflow(contents=["第一章权威正文。"])
        )
        grounding = ChapterWorkflowGroundingService(
            self.novel_service,
            manuscript_storage=self.manuscript_storage,
        )
        request = ChapterWorkflowRequest(
            user_id=self.project.user_id,
            novel_id=self.project.novel_id,
            instruction="写第二章。",
            chapter_plan_id=self.chapter_two.chapter_plan_id,
            chapter_plan_revision=self.chapter_two.revision,
        )

        candidate_only = grounding.resolve(request)
        self.assertEqual(
            candidate_only.metadata["accepted_manuscript_chapter_ids"],
            [],
        )
        self.assertNotIn("第一章权威正文", candidate_only.message)

        self.service.accept_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        accepted = grounding.resolve(request)
        self.assertEqual(
            accepted.metadata["accepted_manuscript_chapter_ids"],
            [imported.chapter.manuscript_chapter_id],
        )
        self.assertEqual(
            accepted.metadata["accepted_manuscript_revisions"],
            [1],
        )
        self.assertIn("第一章权威正文", accepted.message)
        self.assertLessEqual(
            accepted.metadata["grounding_context_chars"],
            3600,
        )

    def test_grounding_budget_preserves_accepted_continuity(self) -> None:
        content = "权威连续性标记：旧堤已经决口。" + ("潮水上涨。" * 2000)
        imported = self.import_run(
            self.create_workflow(contents=[content])
        )
        self.service.accept_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        grounding = ChapterWorkflowGroundingService(
            self.novel_service,
            manuscript_storage=self.manuscript_storage,
        ).resolve(
            ChapterWorkflowRequest(
                user_id=self.project.user_id,
                novel_id=self.project.novel_id,
                instruction="写第二章。",
                chapter_plan_id=self.chapter_two.chapter_plan_id,
                chapter_plan_revision=self.chapter_two.revision,
            )
        )
        self.assertIn("权威连续性标记", grounding.message)
        self.assertIn(self.chapter_two.chapter_plan_id, grounding.message)
        self.assertLessEqual(len(grounding.message), 3600)

    def test_new_candidate_does_not_replace_accepted_continuity(self) -> None:
        first = self.import_run(
            self.create_workflow(contents=["已接受的第一章正文。"])
        )
        chapter_id = first.chapter.manuscript_chapter_id
        accepted = self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        second_run = self.create_workflow(contents=["尚未接受的新候选。"])
        self.import_run(
            second_run,
            expected=accepted.chapter.revision,
        )

        continuity = self.manuscript_storage.list_accepted_before(
            self.project.novel_id,
            2,
        )
        self.assertEqual(len(continuity), 1)
        self.assertEqual(continuity[0]["accepted_revision"], 1)
        self.assertEqual(continuity[0]["content"], "已接受的第一章正文。")


class ManuscriptApiTests(ManuscriptFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        from app.api.v1 import manuscripts

        self.module = manuscripts
        self.original_service = manuscripts.service
        self.original_projection_service = manuscripts.projection_service
        manuscripts.service = self.service
        manuscripts.projection_service = type(
            "NoopProjectionService",
            (),
            {
                "project_chapter": staticmethod(
                    lambda manuscript_chapter_id: _zero_async()
                )
            },
        )()
        app = FastAPI()
        app.include_router(manuscripts.router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.module.service = self.original_service
        self.module.projection_service = self.original_projection_service
        super().tearDown()

    def test_import_list_get_revisions_and_accept_api(self) -> None:
        run_id = self.create_workflow(contents=["API 正文。"])
        imported = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            "/manuscript/chapters/import-workflow",
            json={"workflow_run_id": run_id},
        )
        self.assertEqual(imported.status_code, 201)
        data = imported.json()["data"]
        chapter_id = data["chapter"]["manuscript_chapter_id"]
        self.assertIsNone(data["chapter"]["accepted_revision"])

        listed = self.client.get(
            f"/api/v1/novels/{self.project.novel_id}"
            "/manuscript/chapters"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["data"]), 1)

        revisions = self.client.get(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/manuscript/chapters/{chapter_id}/revisions"
        )
        self.assertEqual(revisions.status_code, 200)
        self.assertEqual(revisions.json()["data"][0]["revision"], 1)

        accepted = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/manuscript/chapters/{chapter_id}/revisions/1/accept",
            json={"expected_manuscript_revision": 1},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["data"]["changed"])

        detail = self.client.get(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/manuscript/chapters/{chapter_id}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.json()["data"]["accepted"]["content"],
            "API 正文。",
        )

    def test_api_maps_missing_run_and_revision_conflict(self) -> None:
        missing = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            "/manuscript/chapters/import-workflow",
            json={"workflow_run_id": "missing-run"},
        )
        self.assertEqual(missing.status_code, 404)

        run_id = self.create_workflow(contents=["候选。"])
        imported = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            "/manuscript/chapters/import-workflow",
            json={"workflow_run_id": run_id},
        ).json()["data"]
        chapter_id = imported["chapter"]["manuscript_chapter_id"]
        conflict = self.client.post(
            f"/api/v1/novels/{self.project.novel_id}"
            f"/manuscript/chapters/{chapter_id}/revisions/1/accept",
            json={"expected_manuscript_revision": 99},
        )
        self.assertEqual(conflict.status_code, 409)

    def test_openapi_registers_manuscript_routes(self) -> None:
        paths = self.client.app.openapi()["paths"]
        prefix = f"/api/v1/novels/{{novel_id}}/manuscript/chapters"
        self.assertIn(prefix, paths)
        self.assertIn(prefix + "/import-workflow", paths)
        self.assertIn(
            prefix
            + "/{manuscript_chapter_id}/revisions/{revision}/accept",
            paths,
        )
        projection = (
            prefix
            + "/{manuscript_chapter_id}/revisions/{revision}"
            "/fact-projection"
        )
        self.assertIn(projection, paths)
        self.assertIn(projection + "/retry", paths)


if __name__ == "__main__":
    unittest.main()
