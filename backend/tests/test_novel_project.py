from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.novels.schemas import (
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


class NovelProjectStorageTests(unittest.TestCase):

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

    def create_project(
        self,
        *,
        user_id: str = "user-a",
        title: str = "星海余烬",
    ):
        return self.storage.create_project(
            NovelProjectCreate(
                user_id=user_id,
                title=title,
                genre="科幻",
                premise="失落舰队寻找故乡。",
                target_word_count=800000,
                style_guide={
                    "pov": "third_person_limited",
                },
                constraints=[
                    "不使用系统流",
                    "科技规则保持一致",
                ],
            )
        )

    def test_schema_is_initialized(self) -> None:
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
        self.assertIn("novel_projects", tables)
        self.assertIn("story_bibles", tables)
        self.assertIn(
            "story_bible_revisions",
            tables,
        )

    def test_create_project_creates_story_bible(self) -> None:
        project = self.create_project()
        bible = self.storage.get_story_bible(
            project.novel_id
        )
        self.assertEqual(project.revision, 1)
        self.assertEqual(
            project.story_bible_revision,
            1,
        )
        self.assertEqual(bible.revision, 1)
        self.assertEqual(bible.world, {})
        self.assertEqual(bible.characters, [])

    def test_project_round_trip_preserves_structured_fields(self) -> None:
        project = self.create_project()
        loaded = self.storage.get_project(
            project.novel_id
        )
        self.assertEqual(
            loaded.style_guide["pov"],
            "third_person_limited",
        )
        self.assertEqual(
            loaded.constraints,
            [
                "不使用系统流",
                "科技规则保持一致",
            ],
        )
        self.assertEqual(
            loaded.target_word_count,
            800000,
        )

    def test_list_projects_filters_user_and_status(self) -> None:
        first = self.create_project(
            user_id="user-a",
            title="A",
        )
        second = self.create_project(
            user_id="user-b",
            title="B",
        )
        self.storage.update_project(
            second.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                status="writing",
            ),
        )
        user_a = self.storage.list_projects(
            user_id="user-a"
        )
        writing = self.storage.list_projects(
            status="writing"
        )
        self.assertEqual(
            [item.novel_id for item in user_a],
            [first.novel_id],
        )
        self.assertEqual(
            [item.novel_id for item in writing],
            [second.novel_id],
        )

    def test_project_update_bumps_revision(self) -> None:
        project = self.create_project()
        updated = self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                title="星海余烬·第一部",
                status="writing",
            ),
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(
            updated.title,
            "星海余烬·第一部",
        )
        self.assertEqual(
            updated.status,
            "writing",
        )

    def test_project_revision_conflict_is_rejected(self) -> None:
        project = self.create_project()
        self.storage.update_project(
            project.novel_id,
            NovelProjectUpdate(
                expected_revision=1,
                title="新标题",
            ),
        )
        with self.assertRaises(
            NovelRevisionConflictError
        ):
            self.storage.update_project(
                project.novel_id,
                NovelProjectUpdate(
                    expected_revision=1,
                    title="过期写入",
                ),
            )

    def test_story_bible_update_bumps_revision_and_preserves_partial_data(self) -> None:
        project = self.create_project()
        first = self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                world={
                    "era": "星历417年",
                },
                themes=["归乡", "身份"],
            ),
        )
        second = self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=2,
                characters=[
                    {
                        "id": "char-lin",
                        "name": "林岚",
                        "role": "protagonist",
                    }
                ],
            ),
        )
        self.assertEqual(first.revision, 2)
        self.assertEqual(second.revision, 3)
        self.assertEqual(
            second.world["era"],
            "星历417年",
        )
        self.assertEqual(
            second.themes,
            ["归乡", "身份"],
        )
        self.assertEqual(
            second.characters[0]["id"],
            "char-lin",
        )

    def test_story_bible_revision_conflict_is_rejected(self) -> None:
        project = self.create_project()
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                world={"planet": "苍蓝星"},
            ),
        )
        with self.assertRaises(
            NovelRevisionConflictError
        ):
            self.storage.update_story_bible(
                project.novel_id,
                StoryBibleUpdate(
                    expected_revision=1,
                    world={"planet": "旧数据"},
                ),
            )

    def test_story_bible_revision_history_is_immutable(self) -> None:
        project = self.create_project()
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                world={"era": "第一纪元"},
            ),
        )
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=2,
                world={"era": "第二纪元"},
            ),
        )
        revisions = (
            self.storage
            .list_story_bible_revisions(
                project.novel_id
            )
        )
        self.assertEqual(
            [item.revision for item in revisions],
            [3, 2, 1],
        )
        old = self.storage.get_story_bible_revision(
            project.novel_id,
            2,
        )
        self.assertEqual(
            old.snapshot.world["era"],
            "第一纪元",
        )

    def test_project_reports_current_story_bible_revision(self) -> None:
        project = self.create_project()
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                themes=["选择"],
            ),
        )
        loaded = self.storage.get_project(
            project.novel_id
        )
        self.assertEqual(
            loaded.story_bible_revision,
            2,
        )

    def test_storage_survives_reopen(self) -> None:
        project = self.create_project()
        self.storage.update_story_bible(
            project.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                rules=[
                    {
                        "name": "跃迁限制",
                        "value": "恒星引力井外",
                    }
                ],
            ),
        )
        reopened = NovelProjectStorage(
            self.db_path
        )
        loaded = reopened.get_project(
            project.novel_id
        )
        bible = reopened.get_story_bible(
            project.novel_id
        )
        self.assertEqual(
            loaded.novel_id,
            project.novel_id,
        )
        self.assertEqual(
            bible.rules[0]["name"],
            "跃迁限制",
        )

    def test_unknown_project_is_rejected(self) -> None:
        with self.assertRaises(
            NovelProjectNotFoundError
        ):
            self.storage.get_project(
                "missing-novel"
            )
        with self.assertRaises(
            NovelProjectNotFoundError
        ):
            self.storage.get_story_bible(
                "missing-novel"
            )


class NovelProjectApiTests(unittest.TestCase):

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

    def test_api_create_get_and_update_project(self) -> None:
        created = self.client.post(
            "/api/v1/novels",
            json={
                "user_id": "api-user",
                "title": "雾都回声",
                "genre": "悬疑",
            },
        )
        self.assertEqual(
            created.status_code,
            201,
        )
        project = created.json()["data"]
        novel_id = project["novel_id"]

        loaded = self.client.get(
            f"/api/v1/novels/{novel_id}"
        )
        self.assertEqual(loaded.status_code, 200)

        updated = self.client.patch(
            f"/api/v1/novels/{novel_id}",
            json={
                "expected_revision": 1,
                "status": "writing",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            updated.json()["data"]["revision"],
            2,
        )

    def test_api_story_bible_conflict_returns_409(self) -> None:
        created = self.client.post(
            "/api/v1/novels",
            json={
                "user_id": "api-user",
                "title": "冲突测试",
            },
        ).json()["data"]
        novel_id = created["novel_id"]

        first = self.client.put(
            f"/api/v1/novels/{novel_id}/story-bible",
            json={
                "expected_revision": 1,
                "themes": ["时间"],
            },
        )
        self.assertEqual(first.status_code, 200)

        stale = self.client.put(
            f"/api/v1/novels/{novel_id}/story-bible",
            json={
                "expected_revision": 1,
                "themes": ["覆盖"],
            },
        )
        self.assertEqual(stale.status_code, 409)


class NovelProjectOpenApiTests(unittest.TestCase):

    def test_novel_routes_are_registered(self) -> None:
        from app.main import app

        paths = app.openapi()["paths"]
        expected = {
            "/api/v1/novels",
            "/api/v1/novels/{novel_id}",
            (
                "/api/v1/novels/{novel_id}"
                "/story-bible"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/story-bible/revisions"
            ),
            (
                "/api/v1/novels/{novel_id}"
                "/story-bible/revisions/{revision}"
            ),
        }
        self.assertTrue(
            expected.issubset(paths)
        )


if __name__ == "__main__":
    unittest.main()
