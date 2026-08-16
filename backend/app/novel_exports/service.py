from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from app.manuscripts.service import ManuscriptService
from app.manuscripts.storage import ManuscriptNotFoundError
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectNotFoundError
from app.version import APP_VERSION


EXPORT_FORMAT = "novelforge-novel-export"
EXPORT_FORMAT_VERSION = 1
PAGE_SIZE = 500
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
T = TypeVar("T")


class NovelExportNotFoundError(LookupError):
    pass


class NovelExportConflictError(RuntimeError):
    pass


class NovelExportIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class NovelExportBundle:
    content: bytes
    filename: str
    manifest_sha256: str
    file_count: int
    accepted_chapter_count: int


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _model(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _all_pages(loader: Callable[..., list[T]]) -> list[T]:
    result: list[T] = []
    offset = 0
    while True:
        page = loader(limit=PAGE_SIZE, offset=offset)
        result.extend(page)
        if len(page) < PAGE_SIZE:
            return result
        offset += len(page)


class NovelExportService:
    """Build a read-only, deterministic ZIP from one Novel authority scope."""

    def __init__(
        self,
        novel_service: NovelProjectService | None = None,
        manuscript_service: ManuscriptService | None = None,
    ) -> None:
        self.novel_service = novel_service or NovelProjectService()
        self.manuscript_service = manuscript_service or ManuscriptService()

    def _load_snapshot(self, novel_id: str) -> dict[str, Any]:
        try:
            project = self.novel_service.get_project(novel_id)
            story_bible = self.novel_service.get_story_bible(novel_id)
            novel_plan = self.novel_service.get_novel_plan(novel_id)
            entities = _all_pages(
                lambda **page: self.novel_service.list_entities(
                    novel_id,
                    **page,
                )
            )
            story_arcs = _all_pages(
                lambda **page: self.novel_service.list_story_arcs(
                    novel_id,
                    **page,
                )
            )
            chapter_plans = _all_pages(
                lambda **page: self.novel_service.list_chapter_plans(
                    novel_id,
                    **page,
                )
            )
            manuscript_chapters = _all_pages(
                lambda **page: self.manuscript_service.list_chapters(
                    novel_id,
                    **page,
                )
            )
        except (NovelProjectNotFoundError, ManuscriptNotFoundError) as exc:
            raise NovelExportNotFoundError(
                f"Novel Project not found: {novel_id}"
            ) from exc

        accepted = []
        for chapter in manuscript_chapters:
            if chapter.accepted_revision is None:
                continue
            detail = self.manuscript_service.get_chapter(
                novel_id,
                chapter.manuscript_chapter_id,
            )
            if detail.accepted is None:
                raise NovelExportIntegrityError(
                    "Accepted Manuscript pointer has no revision: "
                    f"{chapter.manuscript_chapter_id}"
                )
            accepted.append((chapter, detail.accepted))

        return {
            "project": project,
            "story_bible": story_bible,
            "novel_plan": novel_plan,
            "entities": entities,
            "story_arcs": story_arcs,
            "chapter_plans": chapter_plans,
            "manuscript_chapters": manuscript_chapters,
            "accepted": accepted,
        }

    @staticmethod
    def _snapshot_token(snapshot: dict[str, Any]) -> str:
        value = {
            "project": [
                snapshot["project"].novel_id,
                snapshot["project"].revision,
                snapshot["project"].story_bible_revision,
            ],
            "story_bible": snapshot["story_bible"].revision,
            "novel_plan": snapshot["novel_plan"].revision,
            "entities": [
                [item.entity_id, item.revision]
                for item in snapshot["entities"]
            ],
            "story_arcs": [
                [item.arc_id, item.revision]
                for item in snapshot["story_arcs"]
            ],
            "chapter_plans": [
                [item.chapter_plan_id, item.revision]
                for item in snapshot["chapter_plans"]
            ],
            "manuscript_chapters": [
                [
                    item.manuscript_chapter_id,
                    item.revision,
                    item.latest_revision,
                    item.accepted_revision,
                ]
                for item in snapshot["manuscript_chapters"]
            ],
        }
        return _sha256(_json_bytes(value))

    @staticmethod
    def _chapter_title(chapter_plan: Any | None, number: int) -> str:
        title = str(getattr(chapter_plan, "title", "") or "").strip()
        return title or f"第 {number} 章"

    def _payload_files(self, snapshot: dict[str, Any]) -> dict[str, bytes]:
        project = snapshot["project"]
        chapter_plan_by_id = {
            item.chapter_plan_id: item
            for item in snapshot["chapter_plans"]
        }
        files: dict[str, bytes] = {
            "project.json": _json_bytes(_model(project)),
            "planning/story_bible.json": _json_bytes(
                _model(snapshot["story_bible"])
            ),
            "planning/novel_plan.json": _json_bytes(
                _model(snapshot["novel_plan"])
            ),
            "planning/entities.json": _json_bytes(
                [_model(item) for item in snapshot["entities"]]
            ),
            "planning/story_arcs.json": _json_bytes(
                [_model(item) for item in snapshot["story_arcs"]]
            ),
            "planning/chapter_plans.json": _json_bytes(
                [_model(item) for item in snapshot["chapter_plans"]]
            ),
        }

        index: list[dict[str, Any]] = []
        combined: list[str] = [f"# {project.title}"]
        for chapter, revision in snapshot["accepted"]:
            raw_content = revision.content.encode("utf-8")
            if _sha256(raw_content) != revision.content_hash:
                raise NovelExportIntegrityError(
                    "Accepted Manuscript content hash mismatch: "
                    f"{chapter.manuscript_chapter_id}:{revision.revision}"
                )
            plan = chapter_plan_by_id.get(chapter.chapter_plan_id)
            title = self._chapter_title(plan, chapter.chapter_number)
            path = (
                "manuscript/chapters/"
                f"{chapter.chapter_number:06d}.md"
            )
            markdown = (
                f"# 第 {chapter.chapter_number} 章 {title}\n\n"
                f"{revision.content.strip()}\n"
            )
            files[path] = markdown.encode("utf-8")
            combined.append(markdown.rstrip())
            index.append(
                {
                    "manuscript_chapter_id": chapter.manuscript_chapter_id,
                    "chapter_number": chapter.chapter_number,
                    "title": title,
                    "accepted_revision": revision.revision,
                    "accepted_at": chapter.accepted_at,
                    "content_path": path,
                    "content_sha256": revision.content_hash,
                    "source_workflow_run_id": revision.source_workflow_run_id,
                    "source_workflow_version_id": (
                        revision.source_workflow_version_id
                    ),
                    "source_project_revision": (
                        revision.source_project_revision
                    ),
                    "source_story_bible_revision": (
                        revision.source_story_bible_revision
                    ),
                    "source_novel_plan_revision": (
                        revision.source_novel_plan_revision
                    ),
                    "source_story_arc_id": revision.source_story_arc_id,
                    "source_story_arc_revision": (
                        revision.source_story_arc_revision
                    ),
                    "source_chapter_plan_id": (
                        revision.source_chapter_plan_id
                    ),
                    "source_chapter_plan_revision": (
                        revision.source_chapter_plan_revision
                    ),
                }
            )

        files["manuscript/index.json"] = _json_bytes(index)
        files["manuscript/accepted.md"] = (
            "\n\n".join(combined).rstrip() + "\n"
        ).encode("utf-8")
        return files

    @staticmethod
    def _manifest(
        snapshot: dict[str, Any],
        files: dict[str, bytes],
    ) -> dict[str, Any]:
        project = snapshot["project"]
        return {
            "format": EXPORT_FORMAT,
            "format_version": EXPORT_FORMAT_VERSION,
            "application_version": APP_VERSION,
            "novel": {
                "novel_id": project.novel_id,
                "user_id": project.user_id,
                "title": project.title,
                "project_revision": project.revision,
                "story_bible_revision": project.story_bible_revision,
                "novel_plan_revision": snapshot["novel_plan"].revision,
            },
            "selection": {
                "manuscript": "accepted_only",
                "planning": "current_revisions",
            },
            "counts": {
                "entities": len(snapshot["entities"]),
                "story_arcs": len(snapshot["story_arcs"]),
                "chapter_plans": len(snapshot["chapter_plans"]),
                "accepted_manuscript_chapters": len(snapshot["accepted"]),
            },
            "files": [
                {
                    "path": path,
                    "bytes": len(content),
                    "sha256": _sha256(content),
                }
                for path, content in sorted(files.items())
            ],
        }

    @staticmethod
    def _zip(files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path, content in sorted(files.items()):
                info = zipfile.ZipInfo(path, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content, compresslevel=9)
        return buffer.getvalue()

    @staticmethod
    def _filename(novel_id: str) -> str:
        safe_id = _SAFE_FILENAME.sub("-", novel_id).strip(".-")
        if not safe_id:
            safe_id = "novel"
        return f"novelforge-{safe_id[:128]}.zip"

    def export(self, novel_id: str) -> NovelExportBundle:
        snapshot = self._load_snapshot(novel_id)
        token = self._snapshot_token(snapshot)
        payload_files = self._payload_files(snapshot)
        manifest_bytes = _json_bytes(self._manifest(snapshot, payload_files))

        verification = self._load_snapshot(novel_id)
        if self._snapshot_token(verification) != token:
            raise NovelExportConflictError(
                "Novel changed while the export snapshot was being built."
            )

        archive_files = {"manifest.json": manifest_bytes, **payload_files}
        return NovelExportBundle(
            content=self._zip(archive_files),
            filename=self._filename(novel_id),
            manifest_sha256=_sha256(manifest_bytes),
            file_count=len(archive_files),
            accepted_chapter_count=len(snapshot["accepted"]),
        )
