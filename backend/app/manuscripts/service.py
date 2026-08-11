from __future__ import annotations

import hashlib

from typing import Any

from app.workflows.storage import WorkflowRunStorage

from .schemas import (
    ManuscriptAcceptRequest,
    ManuscriptAcceptResult,
    ManuscriptChapter,
    ManuscriptChapterDetail,
    ManuscriptImportRequest,
    ManuscriptImportResult,
    ManuscriptRevision,
)
from .storage import (
    ManuscriptConflictError,
    ManuscriptNotFoundError,
    ManuscriptStorage,
)


class ManuscriptService:
    def __init__(
        self,
        storage: ManuscriptStorage | None = None,
        workflow_storage: WorkflowRunStorage | None = None,
    ) -> None:
        self.storage = storage or ManuscriptStorage()
        self.workflow_storage = workflow_storage or WorkflowRunStorage()

    @staticmethod
    def _workflow_candidate(
        novel_id: str,
        run: dict[str, Any],
    ) -> dict[str, Any]:
        if run["novel_id"] != novel_id:
            raise ManuscriptConflictError(
                "Workflow Run belongs to a different Novel Project."
            )
        if (
            run["execution_status"] != "succeeded"
            or not run["quality_gate_passed"]
            or run["workflow_status"] != "completed"
        ):
            raise ManuscriptConflictError(
                "Only a completed, quality-gate-passed Workflow Run "
                "can be imported as a manuscript candidate."
            )

        request = run.get("request") or {}
        result = run.get("result") or {}
        metadata = result.get("metadata") or {}
        chapter_plan_id = request.get("chapter_plan_id")
        chapter_plan_revision = request.get("chapter_plan_revision")
        if not chapter_plan_id or chapter_plan_revision is None:
            raise ManuscriptConflictError(
                "Workflow Run has no Chapter Plan binding."
            )
        if (
            metadata.get("grounding_mode") != "chapter_plan"
            or not metadata.get("planning_freshness_validated")
        ):
            raise ManuscriptConflictError(
                "Workflow Run has no validated Chapter Plan grounding."
            )
        if (
            metadata.get("chapter_plan_id") != chapter_plan_id
            or int(metadata.get("chapter_plan_revision", 0))
            != int(chapter_plan_revision)
        ):
            raise ManuscriptConflictError(
                "Workflow Run grounding does not match its persisted "
                "Chapter Plan binding."
            )

        required_metadata = (
            "source_project_revision",
            "source_story_bible_revision",
            "novel_plan_revision",
            "story_arc_id",
            "story_arc_revision",
        )
        missing = [
            key
            for key in required_metadata
            if metadata.get(key) is None
        ]
        if missing:
            raise ManuscriptConflictError(
                "Workflow Run grounding is missing source metadata: "
                + ", ".join(missing)
            )

        final_content = str(result.get("final_content") or "")
        if not final_content.strip():
            raise ManuscriptConflictError(
                "Workflow Run has no non-empty final content."
            )
        final_hash = hashlib.sha256(
            final_content.encode("utf-8")
        ).hexdigest()
        workflow_versions = list(run.get("versions") or [])
        if not workflow_versions:
            raise ManuscriptConflictError(
                "Workflow Run has no persisted chapter versions."
            )
        final_index = None
        for index in range(len(workflow_versions) - 1, -1, -1):
            if workflow_versions[index].get("content_hash") == final_hash:
                final_index = index
                break
        if final_index is None:
            raise ManuscriptConflictError(
                "Workflow final content does not match a persisted "
                "Workflow Chapter Version."
            )

        quality_scores = result.get("quality_scores") or {}
        review_report = result.get("review_report") or {}
        versions = []
        for index, version in enumerate(workflow_versions):
            source_stage = version.get("source_stage")
            if source_stage not in {"draft", "rewrite", "checkpoint"}:
                raise ManuscriptConflictError(
                    f"Unsupported Workflow version stage: {source_stage}"
                )
            approved = index == final_index
            versions.append(
                {
                    "version_id": version["version_id"],
                    "source_stage": source_stage,
                    "round_index": int(version["round_index"]),
                    "content": version["content"],
                    "content_hash": version["content_hash"],
                    "review_status": (
                        "approved" if approved else "superseded"
                    ),
                    "quality_scores": (
                        quality_scores if approved else {}
                    ),
                    "review_summary": (
                        str(review_report.get("summary") or "")
                        if approved
                        else ""
                    ),
                }
            )

        return {
            "novel_id": novel_id,
            "workflow_run_id": run["run_id"],
            "chapter_plan_id": str(chapter_plan_id),
            "source_chapter_plan_revision": int(chapter_plan_revision),
            "source_project_revision": int(
                metadata["source_project_revision"]
            ),
            "source_story_bible_revision": int(
                metadata["source_story_bible_revision"]
            ),
            "source_novel_plan_revision": int(
                metadata["novel_plan_revision"]
            ),
            "source_story_arc_id": str(metadata["story_arc_id"]),
            "source_story_arc_revision": int(
                metadata["story_arc_revision"]
            ),
            "versions": versions,
        }

    def import_workflow_candidate(
        self,
        novel_id: str,
        payload: ManuscriptImportRequest,
    ) -> ManuscriptImportResult:
        try:
            run = self.workflow_storage.get_run(payload.workflow_run_id)
        except KeyError as exc:
            raise ManuscriptNotFoundError(str(exc)) from exc
        candidate = self._workflow_candidate(novel_id, run)
        return self.storage.import_workflow_candidate(
            candidate,
            expected_manuscript_revision=(
                payload.expected_manuscript_revision
            ),
        )

    def accept_revision(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        revision: int,
        payload: ManuscriptAcceptRequest,
    ) -> ManuscriptAcceptResult:
        return self.storage.accept_revision(
            novel_id,
            manuscript_chapter_id,
            revision,
            expected_manuscript_revision=(
                payload.expected_manuscript_revision
            ),
        )

    def list_chapters(
        self,
        novel_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ManuscriptChapter]:
        return self.storage.list_chapters(
            novel_id,
            limit=limit,
            offset=offset,
        )

    def get_chapter(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
    ) -> ManuscriptChapterDetail:
        return self.storage.get_chapter(
            novel_id,
            manuscript_chapter_id,
        )

    def list_revisions(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        *,
        limit: int = 100,
    ) -> list[ManuscriptRevision]:
        return self.storage.list_revisions(
            novel_id,
            manuscript_chapter_id,
            limit=limit,
        )

    def get_revision(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        revision: int,
    ) -> ManuscriptRevision:
        return self.storage.get_revision(
            novel_id,
            manuscript_chapter_id,
            revision,
        )
