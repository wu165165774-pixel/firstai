from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import unittest
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import exports as exports_api
from app.manuscripts.schemas import ManuscriptAcceptRequest
from app.novel_exports.service import (
    EXPORT_FORMAT,
    EXPORT_FORMAT_VERSION,
    NovelExportConflictError,
    NovelExportIntegrityError,
    NovelExportService,
)
from app.novels.schemas import NovelProjectCreate
from app.version import APP_VERSION
from test_manuscripts import ManuscriptFixture


class ChangingExportService(NovelExportService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.loads = 0

    def _load_snapshot(self, novel_id: str):
        snapshot = super()._load_snapshot(novel_id)
        self.loads += 1
        if self.loads == 2:
            snapshot["project"] = snapshot["project"].model_copy(
                update={"revision": snapshot["project"].revision + 1}
            )
        return snapshot


class NovelExportTests(ManuscriptFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        imported = self.import_run(
            self.create_workflow(
                chapter=self.chapter_one,
                contents=["不应导出的草稿。", "第一章已接受正文。"],
            )
        )
        self.service.accept_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            imported.imported_revisions[-1].revision,
            ManuscriptAcceptRequest(
                expected_manuscript_revision=imported.chapter.revision
            ),
        )
        self.import_run(
            self.create_workflow(
                chapter=self.chapter_two,
                contents=["第二章未接受候选。"],
            )
        )
        self.exporter = NovelExportService(
            self.novel_service,
            self.service,
        )

    @staticmethod
    def _open(bundle):
        return zipfile.ZipFile(io.BytesIO(bundle.content))

    def test_export_contains_current_planning_and_only_accepted_text(self) -> None:
        bundle = self.exporter.export(self.project.novel_id)

        self.assertEqual(bundle.accepted_chapter_count, 1)
        self.assertEqual(
            bundle.filename,
            f"novelforge-{self.project.novel_id}.zip",
        )
        with self._open(bundle) as archive:
            names = set(archive.namelist())
            self.assertIn("project.json", names)
            self.assertIn("planning/story_bible.json", names)
            self.assertIn("planning/entities.json", names)
            self.assertIn("planning/novel_plan.json", names)
            self.assertIn("planning/story_arcs.json", names)
            self.assertIn("planning/chapter_plans.json", names)
            self.assertIn("manuscript/chapters/000001.md", names)
            self.assertIn("manuscript/accepted.md", names)
            self.assertNotIn("manuscript/chapters/000002.md", names)
            combined = archive.read("manuscript/accepted.md").decode()
            self.assertIn("第一章已接受正文。", combined)
            self.assertNotIn("不应导出的草稿。", combined)
            self.assertNotIn("第二章未接受候选。", combined)

            project = json.loads(archive.read("project.json"))
            self.assertEqual(project["novel_id"], self.project.novel_id)
            self.assertEqual(project["user_id"], self.project.user_id)
            plans = json.loads(
                archive.read("planning/chapter_plans.json")
            )
            self.assertEqual(
                [item["chapter_number"] for item in plans],
                [1, 2],
            )

    def test_manifest_verifies_every_payload_member(self) -> None:
        bundle = self.exporter.export(self.project.novel_id)

        with self._open(bundle) as archive:
            manifest_bytes = archive.read("manifest.json")
            manifest = json.loads(manifest_bytes)
            self.assertEqual(manifest["format"], EXPORT_FORMAT)
            self.assertEqual(
                manifest["format_version"],
                EXPORT_FORMAT_VERSION,
            )
            self.assertEqual(
                manifest["application_version"],
                APP_VERSION,
            )
            self.assertEqual(
                hashlib.sha256(manifest_bytes).hexdigest(),
                bundle.manifest_sha256,
            )
            self.assertEqual(
                manifest["selection"]["manuscript"],
                "accepted_only",
            )
            self.assertEqual(
                manifest["counts"]["accepted_manuscript_chapters"],
                1,
            )
            self.assertEqual(
                {item["path"] for item in manifest["files"]},
                set(archive.namelist()) - {"manifest.json"},
            )
            for item in manifest["files"]:
                content = archive.read(item["path"])
                self.assertEqual(len(content), item["bytes"])
                self.assertEqual(
                    hashlib.sha256(content).hexdigest(),
                    item["sha256"],
                )

    def test_same_authority_snapshot_produces_identical_archive(self) -> None:
        first = self.exporter.export(self.project.novel_id)
        second = self.exporter.export(self.project.novel_id)

        self.assertEqual(first.content, second.content)
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)

    def test_export_does_not_include_a_different_novel(self) -> None:
        other = self.novel_service.create_project(
            NovelProjectCreate(
                user_id="other-user",
                title="SHOULD-NOT-LEAK",
                genre="test",
                premise="isolated",
            )
        )

        bundle = self.exporter.export(self.project.novel_id)
        with self._open(bundle) as archive:
            exported_text = "\n".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith((".json", ".md"))
            )
        self.assertNotIn(other.novel_id, exported_text)
        self.assertNotIn("SHOULD-NOT-LEAK", exported_text)

    def test_changed_snapshot_is_rejected(self) -> None:
        exporter = ChangingExportService(
            self.novel_service,
            self.service,
        )
        with self.assertRaises(NovelExportConflictError):
            exporter.export(self.project.novel_id)

    def test_accepted_content_hash_mismatch_is_rejected(self) -> None:
        with sqlite3.connect(self.novel_db) as conn:
            conn.execute(
                """
                UPDATE manuscript_revisions
                SET content = 'tampered'
                WHERE (manuscript_chapter_id, revision) = (
                    SELECT manuscript_chapter_id, accepted_revision
                    FROM manuscript_chapters
                    WHERE novel_id = ? AND chapter_number = 1
                )
                """,
                (self.project.novel_id,),
            )
            conn.commit()

        with self.assertRaises(NovelExportIntegrityError):
            self.exporter.export(self.project.novel_id)

    def test_api_download_headers_and_openapi(self) -> None:
        previous = exports_api.service
        exports_api.service = self.exporter
        api = FastAPI()
        api.include_router(exports_api.router, prefix="/api/v1")
        client = TestClient(api)
        try:
            response = client.get(
                f"/api/v1/novels/{self.project.novel_id}/export"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "application/zip")
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertEqual(
                response.headers["x-novelforge-accepted-chapters"],
                "1",
            )
            self.assertEqual(
                hashlib.sha256(
                    zipfile.ZipFile(io.BytesIO(response.content)).read(
                        "manifest.json"
                    )
                ).hexdigest(),
                response.headers["x-novelforge-manifest-sha256"],
            )
            operation = api.openapi()["paths"][
                "/api/v1/novels/{novel_id}/export"
            ]["get"]
            self.assertIn(
                "application/zip",
                operation["responses"]["200"]["content"],
            )
            missing = client.get("/api/v1/novels/missing/export")
            self.assertEqual(missing.status_code, 404)
        finally:
            exports_api.service = previous


if __name__ == "__main__":
    unittest.main()
