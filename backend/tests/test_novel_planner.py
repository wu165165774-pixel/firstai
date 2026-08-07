from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.novels.schemas import (
    NovelPlanUpdate,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import (
    NovelProjectNotFoundError,
    NovelProjectStorage,
    NovelRevisionConflictError,
)


class NovelPlannerStorageTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp.name) / "novels.db"
        )
        self.storage = NovelProjectStorage(
            self.db_path
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_project(self):
        return self.storage.create_project(
            NovelProjectCreate(
                user_id="planner-user",
                title="星海余烬",
                genre="科幻悬疑",
                premise="失落舰队归乡后发现历史被改写。",
                target_word_count=900000,
            )
        )

    def full_plan_update(
        self,
        expected_revision: int = 1,
    ) -> NovelPlanUpdate:
        return NovelPlanUpdate(
            expected_revision=expected_revision,
            story_premise=(
                "失落舰队归乡后发现整个文明"
                "对他们的存在毫无记录。"
            ),
            core_conflict=(
                "舰队必须在被新政权清除前"
                "找出历史被重写的原因。"
            ),
            central_question=(
                "人是否仍是过去那个自己，"
                "如果所有历史证明都被抹除？"
            ),
            ending_direction=(
                "主角公开历史真相，但选择"
                "保留部分危险技术秘密。"
            ),
            themes=[
                "身份",
                "历史真实性",
                "归乡",
            ],
            main_plot=[
                {
                    "beat_id": "beat-return",
                    "order": 1,
                    "title": "舰队归航",
                    "summary": "故乡拒绝承认舰队身份。",
                    "purpose": "建立核心谜题。",
                    "character_ids": ["char-linlan"],
                },
                {
                    "beat_id": "beat-proof",
                    "order": 2,
                    "title": "寻找原始档案",
                    "summary": "主角找到被封锁的旧档案。",
                    "purpose": "推进历史改写真相。",
                    "character_ids": [
                        "char-linlan",
                        "char-chenmo",
                    ],
                },
            ],
            character_arcs=[
                {
                    "character_id": "char-linlan",
                    "character_name": "林岚",
                    "role": "protagonist",
                    "start_state": "相信档案记录代表真相。",
                    "desire": "证明舰队合法身份。",
                    "need": "接受身份不能只依赖外部证明。",
                    "internal_conflict": "记忆与现实冲突。",
                    "external_conflict": "议会追捕舰队成员。",
                    "midpoint_shift": "发现舰队曾主动参与删档。",
                    "end_state": "主动定义自己与舰队的新身份。",
                    "key_turning_points": [
                        "旧档案出现",
                        "发现舰队责任",
                        "公开真相",
                    ],
                }
            ],
            volume_plans=[
                {
                    "volume_number": 1,
                    "title": "归航",
                    "purpose": "建立世界与核心谜题。",
                    "start_state": "舰队准备回到故乡。",
                    "end_state": "舰队成为通缉目标。",
                    "core_conflict": "证明自身存在。",
                    "climax": "档案馆证据被公开销毁。",
                    "target_word_count": 220000,
                    "major_events": [
                        "舰队归航",
                        "身份审查",
                        "档案馆突袭",
                    ],
                    "character_focus": ["char-linlan"],
                }
            ],
            metadata={
                "planner": "manual-test",
            },
        )

    def test_schema_contains_plan_tables(self) -> None:
        with sqlite3.connect(
            self.db_path
        ) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                    """
                ).fetchall()
            }
        self.assertIn("novel_plans", tables)
        self.assertIn(
            "novel_plan_revisions",
            tables,
        )
        self.assertIn(
            "idx_novel_plan_revisions_time",
            indexes,
        )

    def test_create_project_creates_seeded_plan(self) -> None:
        project = self.create_project()
        plan = self.storage.get_novel_plan(
            project.novel_id
        )
        self.assertEqual(plan.revision, 1)
        self.assertEqual(
            plan.source_project_revision,
            1,
        )
        self.assertEqual(
            plan.source_story_bible_revision,
            1,
        )
        self.assertFalse(plan.is_stale)
        self.assertEqual(
            plan.story_premise,
            project.premise,
        )
        self.assertEqual(plan.main_plot, [])
        self.assertEqual(plan.character_arcs, [])
        self.assertEqual(plan.volume_plans, [])

    def test_init_backfills_missing_plan(self) -> None:
        project = self.create_project()
        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                premise="迁移前的新前提。",
            ),
        )
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                themes=["迁移"],
            ),
        )
        with sqlite3.connect(
            self.db_path
        ) as conn:
            conn.execute(
                "DELETE FROM novel_plan_revisions WHERE novel_id = ?",
                (project.novel_id,),
            )
            conn.execute(
                "DELETE FROM novel_plans WHERE novel_id = ?",
                (project.novel_id,),
            )
            conn.commit()

        reopened = NovelProjectStorage(
            self.db_path
        )
        plan = reopened.get_novel_plan(
            project.novel_id
        )
        revisions = reopened.list_novel_plan_revisions(
            project.novel_id
        )
        self.assertEqual(plan.revision, 1)
        self.assertEqual(
            plan.source_project_revision,
            2,
        )
        self.assertEqual(
            plan.source_story_bible_revision,
            2,
        )
        self.assertEqual(
            plan.story_premise,
            "迁移前的新前提。",
        )
        self.assertFalse(plan.is_stale)
        self.assertEqual(
            [item.revision for item in revisions],
            [1],
        )

    def test_plan_update_round_trips_typed_structure(self) -> None:
        project = self.create_project()
        updated = self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        self.assertEqual(updated.revision, 2)
        self.assertFalse(updated.is_stale)
        self.assertEqual(
            updated.main_plot[0].beat_id,
            "beat-return",
        )
        self.assertEqual(
            updated.character_arcs[0].character_id,
            "char-linlan",
        )
        self.assertEqual(
            updated.volume_plans[0].volume_number,
            1,
        )
        self.assertEqual(
            updated.volume_plans[0].target_word_count,
            220000,
        )

    def test_plan_partial_update_preserves_existing_data(self) -> None:
        project = self.create_project()
        first = self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        second = self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                ending_direction="新的结局方向。",
            ),
        )
        self.assertEqual(first.revision, 2)
        self.assertEqual(second.revision, 3)
        self.assertEqual(
            second.ending_direction,
            "新的结局方向。",
        )
        self.assertEqual(
            second.main_plot[0].beat_id,
            "beat-return",
        )
        self.assertEqual(
            second.character_arcs[0].character_id,
            "char-linlan",
        )

    def test_plan_revision_conflict_is_rejected(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        with self.assertRaises(
            NovelRevisionConflictError
        ):
            self.storage.update_novel_plan(
                project.novel_id,
                NovelPlanUpdate(
                    expected_revision=1,
                    core_conflict="过期写入",
                ),
            )

    def test_plan_revision_history_is_immutable(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                core_conflict="第二版冲突。",
            ),
        )
        revisions = self.storage.list_novel_plan_revisions(
            project.novel_id
        )
        self.assertEqual(
            [item.revision for item in revisions],
            [3, 2, 1],
        )
        old = self.storage.get_novel_plan_revision(
            project.novel_id,
            2,
        )
        self.assertNotEqual(
            old.snapshot.core_conflict,
            "第二版冲突。",
        )
        self.assertEqual(
            old.snapshot.main_plot[0].beat_id,
            "beat-return",
        )

    def test_project_change_marks_plan_stale(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                title="星海余烬·新版",
            ),
        )
        plan = self.storage.get_novel_plan(
            project.novel_id
        )
        self.assertTrue(plan.is_stale)
        self.assertEqual(
            plan.source_project_revision,
            1,
        )

    def test_story_bible_change_marks_plan_stale(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                themes=["身份"],
            ),
        )
        plan = self.storage.get_novel_plan(
            project.novel_id
        )
        self.assertTrue(plan.is_stale)
        self.assertEqual(
            plan.source_story_bible_revision,
            1,
        )

    def test_plan_update_refreshes_source_revisions(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                genre="硬科幻",
            ),
        )
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                themes=["身份", "真相"],
            ),
        )
        stale = self.storage.get_novel_plan(
            project.novel_id
        )
        self.assertTrue(stale.is_stale)

        refreshed = self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                metadata={"reviewed": True},
            ),
        )
        self.assertFalse(refreshed.is_stale)
        self.assertEqual(
            refreshed.source_project_revision,
            2,
        )
        self.assertEqual(
            refreshed.source_story_bible_revision,
            2,
        )

    def test_revision_snapshots_pin_source_revisions(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                world={"era": "星历417年"},
            ),
        )
        self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                central_question="修订后的核心问题。",
            ),
        )
        revision2 = self.storage.get_novel_plan_revision(
            project.novel_id,
            2,
        )
        revision3 = self.storage.get_novel_plan_revision(
            project.novel_id,
            3,
        )
        self.assertEqual(
            revision2.snapshot.source_story_bible_revision,
            1,
        )
        self.assertEqual(
            revision3.snapshot.source_story_bible_revision,
            2,
        )

    def test_storage_survives_reopen(self) -> None:
        project = self.create_project()
        self.storage.update_novel_plan(
            project.novel_id,
            self.full_plan_update(),
        )
        reopened = NovelProjectStorage(
            self.db_path
        )
        plan = reopened.get_novel_plan(
            project.novel_id
        )
        revisions = reopened.list_novel_plan_revisions(
            project.novel_id
        )
        self.assertEqual(plan.revision, 2)
        self.assertEqual(
            plan.volume_plans[0].title,
            "归航",
        )
        self.assertEqual(
            [item.revision for item in revisions],
            [2, 1],
        )

    def test_unknown_project_plan_is_rejected(self) -> None:
        with self.assertRaises(
            NovelProjectNotFoundError
        ):
            self.storage.get_novel_plan(
                "missing-novel"
            )
        with self.assertRaises(
            NovelProjectNotFoundError
        ):
            self.storage.get_novel_plan_revision(
                "missing-novel",
                1,
            )


class NovelPlannerApiTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        storage = NovelProjectStorage(
            str(Path(self.temp.name) / "api.db")
        )
        self.service = NovelProjectService(
            storage
        )

        from app.api.v1 import novels

        self.novels_module = novels
        self.original_service = novels.service
        novels.service = self.service

        app = FastAPI()
        app.include_router(
            novels.router,
            prefix="/api/v1",
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.novels_module.service = (
            self.original_service
        )
        self.temp.cleanup()

    def create_project(self) -> dict:
        response = self.client.post(
            "/api/v1/novels",
            json={
                "user_id": "planner-api",
                "title": "规划 API",
                "premise": "测试总体规划。",
            },
        )
        self.assertEqual(
            response.status_code,
            201,
        )
        return response.json()["data"]

    def test_api_get_and_update_plan(self) -> None:
        project = self.create_project()
        novel_id = project["novel_id"]

        initial = self.client.get(
            f"/api/v1/novels/{novel_id}/plan"
        )
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(
            initial.json()["data"]["revision"],
            1,
        )

        updated = self.client.put(
            f"/api/v1/novels/{novel_id}/plan",
            json={
                "expected_revision": 1,
                "core_conflict": "API 核心冲突",
                "volume_plans": [
                    {
                        "volume_number": 1,
                        "title": "第一卷",
                    }
                ],
            },
        )
        self.assertEqual(updated.status_code, 200)
        data = updated.json()["data"]
        self.assertEqual(data["revision"], 2)
        self.assertEqual(
            data["core_conflict"],
            "API 核心冲突",
        )
        self.assertFalse(data["is_stale"])

    def test_api_plan_conflict_returns_409(self) -> None:
        project = self.create_project()
        novel_id = project["novel_id"]
        first = self.client.put(
            f"/api/v1/novels/{novel_id}/plan",
            json={
                "expected_revision": 1,
                "core_conflict": "第一版",
            },
        )
        self.assertEqual(first.status_code, 200)

        stale = self.client.put(
            f"/api/v1/novels/{novel_id}/plan",
            json={
                "expected_revision": 1,
                "core_conflict": "过期版本",
            },
        )
        self.assertEqual(stale.status_code, 409)
        self.assertIn(
            "Novel Plan revision conflict",
            stale.json()["detail"],
        )

    def test_api_plan_revision_history(self) -> None:
        project = self.create_project()
        novel_id = project["novel_id"]
        self.client.put(
            f"/api/v1/novels/{novel_id}/plan",
            json={
                "expected_revision": 1,
                "central_question": "第一问",
            },
        )
        response = self.client.get(
            (
                f"/api/v1/novels/{novel_id}"
                "/plan/revisions"
            )
        )
        self.assertEqual(response.status_code, 200)
        revisions = response.json()["data"]
        self.assertEqual(
            [item["revision"] for item in revisions],
            [2, 1],
        )


class NovelPlannerOpenApiTests(unittest.TestCase):

    def test_planner_routes_are_registered(self) -> None:
        from app.api.v1 import novels

        app = FastAPI()
        app.include_router(
            novels.router,
            prefix="/api/v1",
        )
        paths = app.openapi()["paths"]
        expected = {
            "/api/v1/novels/{novel_id}/plan",
            (
                "/api/v1/novels/{novel_id}"
                "/plan/revisions"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/plan/revisions/{revision}"
            ),
        }
        self.assertTrue(
            expected.issubset(paths)
        )


if __name__ == "__main__":
    unittest.main()
