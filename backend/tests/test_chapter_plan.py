from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.novels.schemas import (
    ChapterPlanCreate,
    ChapterPlanUpdate,
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


class ChapterPlanStorageTests(unittest.TestCase):

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

    def create_project_and_arcs(self):
        project = self.storage.create_project(
            NovelProjectCreate(
                user_id="chapter-plan-user",
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
                core_conflict="舰队与故乡议会争夺历史解释权。",
                volume_plans=[
                    {
                        "volume_number": 1,
                        "title": "不存在的归乡者",
                    },
                    {
                        "volume_number": 2,
                        "title": "被重写的历史",
                    },
                ],
            ),
        )
        arc1 = self.storage.create_story_arc(
            project.novel_id,
            StoryArcCreate(
                volume_number=1,
                arc_number=1,
                title="归乡审查",
                objective="确认故乡不承认舰队。",
                target_chapter_start=1,
                target_chapter_end=8,
            ),
        )
        arc2 = self.storage.create_story_arc(
            project.novel_id,
            StoryArcCreate(
                volume_number=2,
                arc_number=1,
                title="地下档案",
                objective="找到历史篡改证据。",
                target_chapter_start=31,
                target_chapter_end=42,
            ),
        )
        return project, arc1, arc2

    def chapter_payload(
        self,
        arc_id: str,
        *,
        chapter_number: int = 1,
        title: str = "归乡许可",
    ) -> ChapterPlanCreate:
        return ChapterPlanCreate(
            arc_id=arc_id,
            chapter_number=chapter_number,
            title=title,
            objective="让主角发现身份数据库不存在舰队记录。",
            summary="主角进入归乡审查站并第一次遭到身份否认。",
            pov_character_id="char-linlan",
            pov_character_name="林岚",
            opening_state="相信审查只是手续问题。",
            closing_state="意识到问题可能来自历史记录本身。",
            conflict="亲历事实与官方数据库冲突。",
            reveal="系统显示舰队从未存在。",
            hook="一名审查员偷偷递给主角一张旧纸质记录。",
            scene_beats=[
                {
                    "beat_id": "scene-arrival",
                    "order": 1,
                    "title": "进入审查站",
                    "summary": "舰队代表进入封闭审查区。",
                    "purpose": "建立制度压力。",
                    "character_ids": ["char-linlan"],
                    "location_id": "loc-customs",
                },
                {
                    "beat_id": "scene-denial",
                    "order": 2,
                    "title": "记录不存在",
                    "summary": "系统返回身份不存在。",
                    "purpose": "抛出核心谜题。",
                    "character_ids": ["char-linlan"],
                    "location_id": "loc-customs",
                },
            ],
            continuity_dependencies=[
                "fleet-return-event",
            ],
            target_word_count=5200,
            metadata={"source": "unit-test"},
        )

    def test_schema_contains_chapter_plan_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }

        self.assertIn("chapter_plans", tables)
        self.assertIn("chapter_plan_revisions", tables)
        self.assertIn("idx_chapter_plans_order", indexes)
        self.assertIn("idx_chapter_plans_arc", indexes)
        self.assertIn(
            "idx_chapter_plan_revisions_time",
            indexes,
        )

    def test_create_chapter_captures_four_source_revisions(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        plan = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )

        self.assertEqual(plan.revision, 1)
        self.assertEqual(plan.volume_number, 1)
        self.assertEqual(plan.arc_number, 1)
        self.assertEqual(plan.source_project_revision, 1)
        self.assertEqual(plan.source_story_bible_revision, 1)
        self.assertEqual(plan.source_novel_plan_revision, 2)
        self.assertEqual(plan.source_story_arc_revision, 1)
        self.assertFalse(plan.is_stale)

    def test_list_chapters_is_sorted_and_filterable(self) -> None:
        project, arc1, arc2 = self.create_project_and_arcs()
        third = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(
                arc2.arc_id,
                chapter_number=31,
                title="地下档案入口",
            ),
        )
        second = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(
                arc1.arc_id,
                chapter_number=2,
                title="隔离区",
            ),
        )
        first = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(
                arc1.arc_id,
                chapter_number=1,
            ),
        )

        items = self.storage.list_chapter_plans(
            project.novel_id
        )
        self.assertEqual(
            [item.chapter_plan_id for item in items],
            [
                first.chapter_plan_id,
                second.chapter_plan_id,
                third.chapter_plan_id,
            ],
        )

        arc_items = self.storage.list_chapter_plans(
            project.novel_id,
            arc_id=arc1.arc_id,
        )
        self.assertEqual(
            [item.chapter_number for item in arc_items],
            [1, 2],
        )

        volume_items = self.storage.list_chapter_plans(
            project.novel_id,
            volume_number=2,
        )
        self.assertEqual(
            [item.chapter_number for item in volume_items],
            [31],
        )

    def test_chapter_round_trips_structured_content(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        created = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        loaded = self.storage.get_chapter_plan(
            project.novel_id,
            created.chapter_plan_id,
        )

        self.assertEqual(loaded.pov_character_id, "char-linlan")
        self.assertEqual(len(loaded.scene_beats), 2)
        self.assertEqual(
            loaded.scene_beats[0].beat_id,
            "scene-arrival",
        )
        self.assertEqual(
            loaded.continuity_dependencies,
            ["fleet-return-event"],
        )
        self.assertEqual(loaded.target_word_count, 5200)

    def test_partial_update_increments_revision(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        created = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        updated = self.storage.update_chapter_plan(
            project.novel_id,
            created.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=1,
                hook="旧纸质记录上出现主角童年的签名。",
                target_word_count=5600,
            ),
        )

        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.target_word_count, 5600)
        self.assertEqual(len(updated.scene_beats), 2)
        self.assertIn("童年的签名", updated.hook)

    def test_revision_conflict_is_rejected(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        created = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_chapter_plan(
            project.novel_id,
            created.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=1,
                summary="第二版",
            ),
        )

        with self.assertRaises(NovelRevisionConflictError):
            self.storage.update_chapter_plan(
                project.novel_id,
                created.chapter_plan_id,
                ChapterPlanUpdate(
                    expected_revision=1,
                    summary="过期版本",
                ),
            )

    def test_duplicate_chapter_number_is_rejected(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )

        with self.assertRaises(NovelRevisionConflictError):
            self.storage.create_chapter_plan(
                project.novel_id,
                self.chapter_payload(
                    arc1.arc_id,
                    chapter_number=1,
                    title="重复第一章",
                ),
            )

    def test_rebind_arc_refreshes_arc_source_and_position(self) -> None:
        project, arc1, arc2 = self.create_project_and_arcs()
        created = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_story_arc(
            project.novel_id,
            arc2.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                objective="第二卷 Arc 新目标",
            ),
        )

        rebound = self.storage.update_chapter_plan(
            project.novel_id,
            created.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=1,
                arc_id=arc2.arc_id,
                chapter_number=31,
            ),
        )

        self.assertEqual(rebound.arc_id, arc2.arc_id)
        self.assertEqual(rebound.volume_number, 2)
        self.assertEqual(rebound.arc_number, 1)
        self.assertEqual(rebound.chapter_number, 31)
        self.assertEqual(rebound.source_story_arc_revision, 2)
        self.assertFalse(rebound.is_stale)

    def test_project_change_marks_chapter_stale(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                genre="硬科幻",
            ),
        )
        loaded = self.storage.get_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertTrue(loaded.is_stale)
        self.assertEqual(loaded.source_project_revision, 1)

    def test_story_bible_change_marks_chapter_stale(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                themes=["身份", "历史"],
            ),
        )
        loaded = self.storage.get_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertTrue(loaded.is_stale)
        self.assertEqual(
            loaded.source_story_bible_revision,
            1,
        )

    def test_novel_plan_change_marks_chapter_stale(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_novel_plan(
            project.novel_id,
            NovelPlanUpdate(
                expected_revision=2,
                central_question="新的总体问题",
            ),
        )
        loaded = self.storage.get_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertTrue(loaded.is_stale)
        self.assertEqual(
            loaded.source_novel_plan_revision,
            2,
        )

    def test_story_arc_change_marks_chapter_stale(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_story_arc(
            project.novel_id,
            arc1.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                objective="新的故事弧目标",
            ),
        )
        loaded = self.storage.get_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertTrue(loaded.is_stale)
        self.assertEqual(
            loaded.source_story_arc_revision,
            1,
        )

    def test_update_refreshes_all_four_source_revisions(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
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
                ending_direction="新版总体结局",
            ),
        )
        self.storage.update_story_arc(
            project.novel_id,
            arc1.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                stakes="新版风险",
            ),
        )

        stale = self.storage.get_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertTrue(stale.is_stale)

        refreshed = self.storage.update_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=1,
                metadata={"reviewed": True},
            ),
        )
        self.assertEqual(refreshed.revision, 2)
        self.assertFalse(refreshed.is_stale)
        self.assertEqual(refreshed.source_project_revision, 2)
        self.assertEqual(refreshed.source_story_bible_revision, 2)
        self.assertEqual(refreshed.source_novel_plan_revision, 3)
        self.assertEqual(refreshed.source_story_arc_revision, 2)

    def test_revision_history_is_immutable(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_story_arc(
            project.novel_id,
            arc1.arc_id,
            StoryArcUpdate(
                expected_revision=1,
                objective="Arc 第二版",
            ),
        )
        self.storage.update_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=1,
                objective="Chapter 第二版",
            ),
        )

        revisions = self.storage.list_chapter_plan_revisions(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertEqual(
            [item.revision for item in revisions],
            [2, 1],
        )
        old = self.storage.get_chapter_plan_revision(
            project.novel_id,
            chapter.chapter_plan_id,
            1,
        )
        new = self.storage.get_chapter_plan_revision(
            project.novel_id,
            chapter.chapter_plan_id,
            2,
        )
        self.assertNotEqual(old.snapshot.objective, "Chapter 第二版")
        self.assertEqual(old.snapshot.source_story_arc_revision, 1)
        self.assertEqual(new.snapshot.source_story_arc_revision, 2)
        self.assertFalse(old.snapshot.is_stale)
        self.assertFalse(new.snapshot.is_stale)

    def test_storage_survives_reopen(self) -> None:
        project, arc1, _ = self.create_project_and_arcs()
        chapter = self.storage.create_chapter_plan(
            project.novel_id,
            self.chapter_payload(arc1.arc_id),
        )
        self.storage.update_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
            ChapterPlanUpdate(
                expected_revision=1,
                summary="重启后仍存在",
            ),
        )
        reopened = NovelProjectStorage(self.db_path)
        loaded = reopened.get_chapter_plan(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        revisions = reopened.list_chapter_plan_revisions(
            project.novel_id,
            chapter.chapter_plan_id,
        )
        self.assertEqual(loaded.revision, 2)
        self.assertEqual(loaded.summary, "重启后仍存在")
        self.assertEqual(
            [item.revision for item in revisions],
            [2, 1],
        )

    def test_unknown_project_arc_and_chapter_are_rejected(self) -> None:
        with self.assertRaises(NovelProjectNotFoundError):
            self.storage.create_chapter_plan(
                "missing-novel",
                self.chapter_payload("missing-arc"),
            )

        project, arc1, _ = self.create_project_and_arcs()

        with self.assertRaises(NovelProjectNotFoundError):
            self.storage.create_chapter_plan(
                project.novel_id,
                self.chapter_payload("missing-arc"),
            )

        with self.assertRaises(NovelProjectNotFoundError):
            self.storage.get_chapter_plan(
                project.novel_id,
                "missing-chapter-plan",
            )


class ChapterPlanApiTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        storage = NovelProjectStorage(
            str(Path(self.temp.name) / "api.db")
        )
        self.service = NovelProjectService(storage)

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
        self.novels_module.service = self.original_service
        self.temp.cleanup()

    def create_project_and_arc(self) -> tuple[dict, dict]:
        project_response = self.client.post(
            "/api/v1/novels",
            json={
                "user_id": "chapter-api",
                "title": "Chapter Plan API",
                "premise": "测试 Chapter Plan。",
            },
        )
        self.assertEqual(project_response.status_code, 201)
        project = project_response.json()["data"]
        novel_id = project["novel_id"]

        arc_response = self.client.post(
            f"/api/v1/novels/{novel_id}/arcs",
            json={
                "volume_number": 1,
                "arc_number": 1,
                "title": "第一故事弧",
            },
        )
        self.assertEqual(arc_response.status_code, 201)
        return project, arc_response.json()["data"]

    def create_chapter(self, novel_id: str, arc_id: str) -> dict:
        response = self.client.post(
            f"/api/v1/novels/{novel_id}/chapter-plans",
            json={
                "arc_id": arc_id,
                "chapter_number": 1,
                "title": "第一章",
                "objective": "验证 API",
                "scene_beats": [
                    {
                        "beat_id": "beat-1",
                        "order": 1,
                        "title": "开场",
                    }
                ],
                "target_word_count": 5000,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]

    def test_api_create_list_filter_and_get(self) -> None:
        project, arc = self.create_project_and_arc()
        novel_id = project["novel_id"]
        chapter = self.create_chapter(novel_id, arc["arc_id"])

        listed = self.client.get(
            f"/api/v1/novels/{novel_id}/chapter-plans"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["data"]), 1)

        filtered = self.client.get(
            f"/api/v1/novels/{novel_id}/chapter-plans",
            params={"arc_id": arc["arc_id"]},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(filtered.json()["data"]), 1)

        loaded = self.client.get(
            (
                f"/api/v1/novels/{novel_id}/chapter-plans/"
                f"{chapter['chapter_plan_id']}"
            )
        )
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["data"]["title"], "第一章")

    def test_api_update_conflict_and_revision_history(self) -> None:
        project, arc = self.create_project_and_arc()
        novel_id = project["novel_id"]
        chapter = self.create_chapter(novel_id, arc["arc_id"])
        chapter_id = chapter["chapter_plan_id"]

        updated = self.client.put(
            f"/api/v1/novels/{novel_id}/chapter-plans/{chapter_id}",
            json={
                "expected_revision": 1,
                "hook": "第二版钩子",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["data"]["revision"], 2)

        stale = self.client.put(
            f"/api/v1/novels/{novel_id}/chapter-plans/{chapter_id}",
            json={
                "expected_revision": 1,
                "hook": "过期钩子",
            },
        )
        self.assertEqual(stale.status_code, 409)
        self.assertIn(
            "Chapter Plan revision conflict",
            stale.json()["detail"],
        )

        revisions = self.client.get(
            (
                f"/api/v1/novels/{novel_id}/chapter-plans/"
                f"{chapter_id}/revisions"
            )
        )
        self.assertEqual(revisions.status_code, 200)
        self.assertEqual(
            [item["revision"] for item in revisions.json()["data"]],
            [2, 1],
        )

    def test_api_duplicate_position_returns_409(self) -> None:
        project, arc = self.create_project_and_arc()
        novel_id = project["novel_id"]
        self.create_chapter(novel_id, arc["arc_id"])
        response = self.client.post(
            f"/api/v1/novels/{novel_id}/chapter-plans",
            json={
                "arc_id": arc["arc_id"],
                "chapter_number": 1,
                "title": "重复第一章",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("position conflict", response.json()["detail"])


class ChapterPlanOpenApiTests(unittest.TestCase):

    def test_chapter_plan_routes_and_schema_are_registered(self) -> None:
        from app.api.v1 import novels

        app = FastAPI()
        app.include_router(
            novels.router,
            prefix="/api/v1",
        )
        schema = app.openapi()
        paths = schema["paths"]

        expected = {
            "/api/v1/novels/{novel_id}/chapter-plans",
            (
                "/api/v1/novels/{novel_id}"
                "/chapter-plans/{chapter_plan_id}"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/chapter-plans/{chapter_plan_id}/revisions"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/chapter-plans/{chapter_plan_id}/revisions/{revision}"
            ),
        }
        self.assertTrue(expected.issubset(paths))

        chapter_schema = schema["components"]["schemas"]["ChapterPlan"]
        properties = chapter_schema.get("properties", {})
        required = set(chapter_schema.get("required", []))

        for field in (
            "chapter_plan_id",
            "arc_id",
            "chapter_number",
            "source_project_revision",
            "source_story_bible_revision",
            "source_novel_plan_revision",
            "source_story_arc_revision",
            "is_stale",
        ):
            self.assertIn(field, properties)

        for field in (
            "chapter_plan_id",
            "arc_id",
            "chapter_number",
            "source_project_revision",
            "source_story_bible_revision",
            "source_novel_plan_revision",
            "source_story_arc_revision",
        ):
            self.assertIn(field, required)

        self.assertNotIn("is_stale", required)
        self.assertFalse(properties["is_stale"]["default"])


if __name__ == "__main__":
    unittest.main()
