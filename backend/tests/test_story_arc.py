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
    StoryArcCreate,
    StoryArcUpdate,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import (
    NovelProjectNotFoundError,
    NovelProjectStorage,
    NovelRevisionConflictError,
)


class StoryArcStorageTests(unittest.TestCase):

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
        project = self.storage.create_project(
            NovelProjectCreate(
                user_id="arc-user",
                title="星海余烬",
                genre="科幻悬疑",
                premise="失落舰队归乡后发现历史被改写。",
                target_word_count=900000,
            )
        )
        self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=1,
                story_premise="舰队归乡却被故乡否认。",
                core_conflict="舰队与故乡议会争夺历史解释权。",
                volume_plans=[
                    {
                        "volume_number": 1,
                        "title": "不存在的归乡者",
                        "purpose": "建立身份谜题。",
                    },
                    {
                        "volume_number": 2,
                        "title": "被重写的历史",
                        "purpose": "推进幕后真相。",
                    },
                ],
            ),
        )
        return project

    def arc_payload(
        self,
        *,
        volume_number: int = 1,
        arc_number: int = 1,
        title: str = "归乡审查",
    ) -> StoryArcCreate:
        return StoryArcCreate(
            volume_number=volume_number,
            arc_number=arc_number,
            title=title,
            objective="让舰队确认故乡不承认他们的身份。",
            summary="舰队接受审查并发现所有历史记录都不存在。",
            opening_state="舰队相信自己只是遭遇行政错误。",
            closing_state="舰队意识到历史被系统性改写。",
            core_conflict="舰队身份与官方历史记录冲突。",
            stakes="一旦审查失败，舰队会被认定为非法武装。",
            turning_points=[
                {
                    "turning_point_id": "tp-denial",
                    "order": 1,
                    "title": "身份被拒绝",
                    "description": "官方系统找不到舰队记录。",
                    "consequence": "舰队被隔离。",
                    "character_ids": ["char-linlan"],
                },
                {
                    "turning_point_id": "tp-proof",
                    "order": 2,
                    "title": "旧证据出现",
                    "description": "主角发现一份无法解释的旧纸质档案。",
                    "consequence": "调查转向历史篡改。",
                    "character_ids": [
                        "char-linlan",
                        "char-chenmo",
                    ],
                },
            ],
            character_progression=[
                {
                    "character_id": "char-linlan",
                    "character_name": "林岚",
                    "start_state": "相信官方档案。",
                    "change": "开始怀疑制度记录。",
                    "end_state": "决定独立调查。",
                    "key_moments": [
                        "身份被拒绝",
                        "看到旧档案",
                    ],
                }
            ],
            plot_threads=[
                "舰队身份谜题",
                "档案篡改",
            ],
            dependencies=[],
            target_chapter_start=1,
            target_chapter_end=8,
            metadata={
                "source": "unit-test",
            },
        )

    def test_schema_contains_story_arc_tables(self) -> None:
        with sqlite3.connect(
            self.db_path
        ) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table'
                    """
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='index'
                    """
                ).fetchall()
            }

        self.assertIn("story_arcs", tables)
        self.assertIn("story_arc_revisions", tables)
        self.assertIn("idx_story_arcs_order", indexes)
        self.assertIn("idx_story_arcs_volume", indexes)
        self.assertIn(
            "idx_story_arc_revisions_time",
            indexes,
        )

    def test_create_arc_captures_three_source_revisions(self) -> None:
        project = self.create_project()

        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        self.assertEqual(arc.revision, 1)
        self.assertEqual(
            arc.source_project_revision,
            1,
        )
        self.assertEqual(
            arc.source_story_bible_revision,
            1,
        )
        self.assertEqual(
            arc.source_novel_plan_revision,
            2,
        )
        self.assertFalse(arc.is_stale)

    def test_list_arcs_is_sorted_and_filterable(self) -> None:
        project = self.create_project()

        third = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(
                volume_number=2,
                arc_number=1,
                title="第二卷第一弧",
            ),
        )
        second = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(
                volume_number=1,
                arc_number=2,
                title="第一卷第二弧",
            ),
        )
        first = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(
                volume_number=1,
                arc_number=1,
                title="第一卷第一弧",
            ),
        )

        items = self.storage.list_story_arcs(
            project.novel_id
        )

        self.assertEqual(
            [item.arc_id for item in items],
            [
                first.arc_id,
                second.arc_id,
                third.arc_id,
            ],
        )

        volume_one = self.storage.list_story_arcs(
            project.novel_id,
            volume_number=1,
        )

        self.assertEqual(
            [item.arc_number for item in volume_one],
            [1, 2],
        )

    def test_arc_round_trips_structured_content(self) -> None:
        project = self.create_project()

        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        loaded = self.storage.get_story_arc(
            project.novel_id,
            arc.arc_id,
        )

        self.assertEqual(
            loaded.turning_points[0].turning_point_id,
            "tp-denial",
        )
        self.assertEqual(
            loaded.character_progression[0].character_id,
            "char-linlan",
        )
        self.assertEqual(
            loaded.plot_threads,
            [
                "舰队身份谜题",
                "档案篡改",
            ],
        )
        self.assertEqual(
            loaded.target_chapter_start,
            1,
        )
        self.assertEqual(
            loaded.target_chapter_end,
            8,
        )

    def test_arc_partial_update_increments_revision(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        updated = self.storage.update_story_arc(
            project.novel_id,
            arc.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                closing_state="舰队决定脱离审查区。",
                target_chapter_end=10,
            ),
        )

        self.assertEqual(updated.revision, 2)
        self.assertEqual(
            updated.closing_state,
            "舰队决定脱离审查区。",
        )
        self.assertEqual(
            updated.target_chapter_end,
            10,
        )
        self.assertEqual(
            updated.turning_points[0].turning_point_id,
            "tp-denial",
        )

    def test_arc_revision_conflict_is_rejected(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )
        self.storage.update_story_arc(
            project.novel_id,
            arc.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                stakes="第一次修改",
            ),
        )

        with self.assertRaises(
            NovelRevisionConflictError
        ):
            self.storage.update_story_arc(
                project.novel_id,
                arc.arc_id,
                StoryArcUpdate(
                    expected_revision=1,
                    stakes="过期修改",
                ),
            )

    def test_duplicate_arc_position_is_rejected(self) -> None:
        project = self.create_project()

        self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        with self.assertRaises(
            NovelRevisionConflictError
        ):
            self.storage.create_story_arc(
                project.novel_id,
                self.arc_payload(
                    title="重复位置",
                ),
            )

    def test_project_change_marks_arc_stale(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                genre="硬科幻",
            ),
        )

        loaded = self.storage.get_story_arc(
            project.novel_id,
            arc.arc_id,
        )

        self.assertTrue(loaded.is_stale)
        self.assertEqual(
            loaded.source_project_revision,
            1,
        )

    def test_story_bible_change_marks_arc_stale(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                themes=["身份", "历史"],
            ),
        )

        loaded = self.storage.get_story_arc(
            project.novel_id,
            arc.arc_id,
        )

        self.assertTrue(loaded.is_stale)
        self.assertEqual(
            loaded.source_story_bible_revision,
            1,
        )

    def test_novel_plan_change_marks_arc_stale(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                ending_direction="新的总体结局。",
            ),
        )

        loaded = self.storage.get_story_arc(
            project.novel_id,
            arc.arc_id,
        )

        self.assertTrue(loaded.is_stale)
        self.assertEqual(
            loaded.source_novel_plan_revision,
            2,
        )

    def test_arc_update_refreshes_all_source_revisions(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                title="星海余烬·新版",
            ),
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
                central_question="新的总体问题。",
            ),
        )

        stale = self.storage.get_story_arc(
            project.novel_id,
            arc.arc_id,
        )
        self.assertTrue(stale.is_stale)

        refreshed = self.storage.update_story_arc(
            project.novel_id,
            arc.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                metadata={"reviewed": True},
            ),
        )

        self.assertEqual(refreshed.revision, 2)
        self.assertFalse(refreshed.is_stale)
        self.assertEqual(
            refreshed.source_project_revision,
            2,
        )
        self.assertEqual(
            refreshed.source_story_bible_revision,
            2,
        )
        self.assertEqual(
            refreshed.source_novel_plan_revision,
            3,
        )

    def test_arc_revision_history_is_immutable(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )

        self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                central_question="新版问题。",
            ),
        )

        self.storage.update_story_arc(
            project.novel_id,
            arc.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                objective="新版 Arc 目标。",
            ),
        )

        revisions = self.storage.list_story_arc_revisions(
            project.novel_id,
            arc.arc_id,
        )

        self.assertEqual(
            [item.revision for item in revisions],
            [2, 1],
        )

        old = self.storage.get_story_arc_revision(
            project.novel_id,
            arc.arc_id,
            1,
        )
        new = self.storage.get_story_arc_revision(
            project.novel_id,
            arc.arc_id,
            2,
        )

        self.assertNotEqual(
            old.snapshot.objective,
            "新版 Arc 目标。",
        )
        self.assertEqual(
            old.snapshot.source_novel_plan_revision,
            2,
        )
        self.assertEqual(
            new.snapshot.source_novel_plan_revision,
            3,
        )
        self.assertFalse(old.snapshot.is_stale)
        self.assertFalse(new.snapshot.is_stale)

    def test_storage_survives_reopen(self) -> None:
        project = self.create_project()
        arc = self.storage.create_story_arc(
            project.novel_id,
            self.arc_payload(),
        )
        self.storage.update_story_arc(
            project.novel_id,
            arc.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                summary="重启后仍需存在。",
            ),
        )

        reopened = NovelProjectStorage(
            self.db_path
        )

        loaded = reopened.get_story_arc(
            project.novel_id,
            arc.arc_id,
        )
        revisions = reopened.list_story_arc_revisions(
            project.novel_id,
            arc.arc_id,
        )

        self.assertEqual(loaded.revision, 2)
        self.assertEqual(
            loaded.summary,
            "重启后仍需存在。",
        )
        self.assertEqual(
            [item.revision for item in revisions],
            [2, 1],
        )

    def test_unknown_project_and_arc_are_rejected(self) -> None:
        with self.assertRaises(
            NovelProjectNotFoundError
        ):
            self.storage.create_story_arc(
                "missing-novel",
                self.arc_payload(),
            )

        project = self.create_project()

        with self.assertRaises(
            NovelProjectNotFoundError
        ):
            self.storage.get_story_arc(
                project.novel_id,
                "missing-arc",
            )


class StoryArcApiTests(unittest.TestCase):

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
                "user_id": "arc-api",
                "title": "Story Arc API",
                "premise": "测试 Story Arc。",
            },
        )
        self.assertEqual(
            response.status_code,
            201,
        )
        return response.json()["data"]

    def create_arc(
        self,
        novel_id: str,
    ) -> dict:
        response = self.client.post(
            f"/api/v1/novels/{novel_id}/arcs",
            json={
                "volume_number": 1,
                "arc_number": 1,
                "title": "第一故事弧",
                "objective": "验证 API。",
                "turning_points": [
                    {
                        "turning_point_id": "tp-1",
                        "order": 1,
                        "title": "转折",
                    }
                ],
                "target_chapter_start": 1,
                "target_chapter_end": 6,
            },
        )
        self.assertEqual(
            response.status_code,
            201,
        )
        return response.json()["data"]

    def test_api_create_list_and_get_arc(self) -> None:
        project = self.create_project()
        novel_id = project["novel_id"]
        arc = self.create_arc(novel_id)

        listed = self.client.get(
            f"/api/v1/novels/{novel_id}/arcs"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            len(listed.json()["data"]),
            1,
        )

        loaded = self.client.get(
            (
                f"/api/v1/novels/{novel_id}"
                f"/arcs/{arc['arc_id']}"
            )
        )
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(
            loaded.json()["data"]["title"],
            "第一故事弧",
        )

    def test_api_update_and_conflict(self) -> None:
        project = self.create_project()
        novel_id = project["novel_id"]
        arc = self.create_arc(novel_id)

        updated = self.client.put(
            (
                f"/api/v1/novels/{novel_id}"
                f"/arcs/{arc['arc_id']}"
            ),
            json={
                "expected_revision": 1,
                "stakes": "新的风险。",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            updated.json()["data"]["revision"],
            2,
        )

        stale = self.client.put(
            (
                f"/api/v1/novels/{novel_id}"
                f"/arcs/{arc['arc_id']}"
            ),
            json={
                "expected_revision": 1,
                "stakes": "过期风险。",
            },
        )
        self.assertEqual(stale.status_code, 409)
        self.assertIn(
            "Story Arc revision conflict",
            stale.json()["detail"],
        )

    def test_api_revision_history(self) -> None:
        project = self.create_project()
        novel_id = project["novel_id"]
        arc = self.create_arc(novel_id)

        self.client.put(
            (
                f"/api/v1/novels/{novel_id}"
                f"/arcs/{arc['arc_id']}"
            ),
            json={
                "expected_revision": 1,
                "summary": "第二版。",
            },
        )

        response = self.client.get(
            (
                f"/api/v1/novels/{novel_id}"
                f"/arcs/{arc['arc_id']}"
                "/revisions"
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                item["revision"]
                for item in response.json()["data"]
            ],
            [2, 1],
        )


class StoryArcOpenApiTests(unittest.TestCase):

    def test_story_arc_routes_and_schema_are_registered(self) -> None:
        from app.api.v1 import novels

        app = FastAPI()
        app.include_router(
            novels.router,
            prefix="/api/v1",
        )

        schema = app.openapi()
        paths = schema["paths"]

        expected = {
            "/api/v1/novels/{novel_id}/arcs",
            (
                "/api/v1/novels/{novel_id}"
                "/arcs/{arc_id}"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/arcs/{arc_id}/revisions"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/arcs/{arc_id}/revisions/{revision}"
            ),
        }

        self.assertTrue(
            expected.issubset(paths)
        )

        arc_schema = (
            schema["components"]["schemas"]["StoryArc"]
        )
        properties = arc_schema.get(
            "properties",
            {},
        )
        required = set(
            arc_schema.get("required", [])
        )

        for field in (
            "revision",
            "source_project_revision",
            "source_story_bible_revision",
            "source_novel_plan_revision",
            "is_stale",
        ):
            self.assertIn(
                field,
                properties,
            )

        for field in (
            "revision",
            "source_project_revision",
            "source_story_bible_revision",
            "source_novel_plan_revision",
        ):
            self.assertIn(
                field,
                required,
            )

        self.assertNotIn(
            "is_stale",
            required,
        )
        self.assertFalse(
            properties["is_stale"]["default"]
        )


if __name__ == "__main__":
    unittest.main()
