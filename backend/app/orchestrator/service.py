from __future__ import annotations

from typing import Any

from app.manuscripts.schemas import ManuscriptImportRequest
from app.manuscripts.service import ManuscriptService
from app.manuscripts.storage import ManuscriptStorage
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectNotFoundError
from app.workflows.async_queue import WorkflowAsyncQueue
from app.workflows.grounding import (
    ChapterWorkflowGroundingConflictError,
    ChapterWorkflowGroundingNotFoundError,
    ChapterWorkflowGroundingService,
)
from app.workflows.schemas import ChapterWorkflowRequest

from .schemas import (
    NovelOrchestrationCreateRequest,
    NovelOrchestrationCreateResult,
    NovelOrchestrationDetail,
    NovelOrchestrationStep,
    NovelOrchestrationSummary,
)
from .storage import (
    NovelOrchestrationConflictError,
    NovelOrchestrationNotFoundError,
    NovelOrchestrationStorage,
)


class NovelOrchestrationService:
    """Coordinate existing Workflow and Manuscript boundaries by chapter."""

    ACTIVE_QUEUE_STATUSES = {
        "queued",
        "retry_wait",
        "running",
        "cancelling",
    }
    TERMINAL_QUEUE_STATUSES = {
        "cancelled",
        "completed",
        "failed",
        "dead_letter",
    }

    def __init__(
        self,
        storage: NovelOrchestrationStorage | None = None,
        workflow_queue: WorkflowAsyncQueue | None = None,
        novel_service: NovelProjectService | None = None,
        manuscript_service: ManuscriptService | None = None,
        grounding_service: ChapterWorkflowGroundingService | None = None,
    ) -> None:
        self.workflow_queue = workflow_queue or WorkflowAsyncQueue()
        self.storage = storage or NovelOrchestrationStorage(
            self.workflow_queue.db_path
        )
        self.novel_service = novel_service or NovelProjectService()
        if manuscript_service is None:
            manuscript_storage = ManuscriptStorage(
                self.novel_service.storage.db_path
            )
            manuscript_service = ManuscriptService(
                manuscript_storage,
                self.workflow_queue.run_storage,
            )
        self.manuscript_service = manuscript_service
        self.grounding_service = grounding_service or (
            ChapterWorkflowGroundingService(
                self.novel_service,
                manuscript_storage=self.manuscript_service.storage,
            )
        )

    @staticmethod
    def _current_step(
        detail: NovelOrchestrationDetail,
    ) -> NovelOrchestrationStep:
        if detail.current_sequence_no is None:
            raise NovelOrchestrationConflictError(
                "Novel Orchestration has no current chapter."
            )
        for step in detail.steps:
            if step.sequence_no == detail.current_sequence_no:
                return step
        raise NovelOrchestrationConflictError(
            "Novel Orchestration current chapter snapshot is missing."
        )

    @staticmethod
    def _assert_owner(
        detail: NovelOrchestrationDetail,
        user_id: str | None,
    ) -> None:
        if user_id is not None and detail.user_id != user_id:
            raise NovelOrchestrationConflictError(
                "user_id does not own this Novel Orchestration."
            )

    @staticmethod
    def _instruction(template: str, step: NovelOrchestrationStep) -> str:
        return template.replace(
            "{chapter_number}",
            str(step.chapter_number),
        ).replace(
            "{chapter_title}",
            step.chapter_title,
        )

    def _workflow_request(
        self,
        detail: NovelOrchestrationDetail,
        step: NovelOrchestrationStep,
    ) -> ChapterWorkflowRequest:
        policy = detail.workflow
        metadata = dict(policy.workflow_metadata)
        metadata.update(
            {
                "orchestration_id": detail.orchestration_id,
                "orchestration_sequence_no": step.sequence_no,
                "orchestration_revision": detail.revision,
            }
        )
        return ChapterWorkflowRequest(
            user_id=detail.user_id,
            novel_id=detail.novel_id,
            instruction=self._instruction(policy.instruction_template, step),
            chapter_plan_id=step.chapter_plan_id,
            chapter_plan_revision=step.chapter_plan_revision,
            provider=policy.provider,
            model=policy.model,
            use_memory=policy.use_memory,
            auto_rewrite=policy.auto_rewrite,
            max_revision_rounds=policy.max_revision_rounds,
            review_retry_attempts=policy.review_retry_attempts,
            review_retry_reasoning_effort=(
                policy.review_retry_reasoning_effort
            ),
            minimum_overall_score=policy.minimum_overall_score,
            minimum_dimension_score=policy.minimum_dimension_score,
            require_all_issues_resolved=policy.require_all_issues_resolved,
            chapter_reasoning_effort=policy.chapter_reasoning_effort,
            review_reasoning_effort=policy.review_reasoning_effort,
            rewrite_reasoning_effort=policy.rewrite_reasoning_effort,
            chapter_temperature=policy.chapter_temperature,
            review_temperature=policy.review_temperature,
            rewrite_temperature=policy.rewrite_temperature,
            chapter_max_tokens=policy.chapter_max_tokens,
            review_max_tokens=policy.review_max_tokens,
            rewrite_max_tokens=policy.rewrite_max_tokens,
            rewrite_on_severities=policy.rewrite_on_severities,
            metadata=metadata,
        )

    def _validate_grounding(self, request: ChapterWorkflowRequest) -> None:
        try:
            self.grounding_service.resolve(request)
        except ChapterWorkflowGroundingNotFoundError as exc:
            raise NovelOrchestrationNotFoundError(str(exc)) from exc
        except ChapterWorkflowGroundingConflictError as exc:
            raise NovelOrchestrationConflictError(str(exc)) from exc

    def _enqueue_current(
        self,
        detail: NovelOrchestrationDetail,
        *,
        retry: bool = False,
        workflow_attempt: int | None = None,
    ) -> NovelOrchestrationDetail:
        allowed_statuses = {"ready", "failed"}
        if retry:
            allowed_statuses.add("waiting_for_acceptance")
        if detail.status not in allowed_statuses:
            raise NovelOrchestrationConflictError(
                "Current orchestration state cannot enqueue a chapter."
            )
        step = self._current_step(detail)
        request = self._workflow_request(detail, step)
        try:
            self._validate_grounding(request)
        except (NovelOrchestrationNotFoundError, NovelOrchestrationConflictError):
            if detail.status != "failed":
                self.storage.mark_failed(
                    detail.novel_id,
                    detail.orchestration_id,
                    expected_revision=detail.revision,
                    error="Chapter planning binding is no longer executable.",
                )
            raise

        attempt = workflow_attempt or max(step.workflow_attempt + 1, 1)
        key = (
            f"orchestrator:{detail.orchestration_id}:"
            f"step:{step.sequence_no}:attempt:{attempt}"
        )
        try:
            run_id, _ = self.workflow_queue.enqueue(
                request,
                idempotency_key=key,
                priority=detail.queue.priority,
                max_attempts=detail.queue.max_attempts,
                retry_base_seconds=detail.queue.retry_base_seconds,
                timeout_seconds=detail.queue.timeout_seconds,
            )
        except Exception as exc:
            if detail.status != "failed":
                self.storage.mark_failed(
                    detail.novel_id,
                    detail.orchestration_id,
                    expected_revision=detail.revision,
                    error=str(exc),
                )
            raise
        return self.storage.attach_workflow(
            detail.novel_id,
            detail.orchestration_id,
            expected_revision=detail.revision,
            workflow_run_id=run_id,
            workflow_attempt=attempt,
            retry=retry,
        )

    def _accepted_snapshot(
        self,
        novel_id: str,
    ) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for chapter in self.manuscript_service.list_chapters(
            novel_id,
            limit=1_000_000,
        ):
            if chapter.accepted_revision is None:
                continue
            detail = self.manuscript_service.get_chapter(
                novel_id,
                chapter.manuscript_chapter_id,
            )
            if detail.accepted is None:
                continue
            result[chapter.chapter_number] = {
                "chapter": chapter,
                "accepted": detail.accepted,
            }
        return result

    def create(
        self,
        novel_id: str,
        payload: NovelOrchestrationCreateRequest,
        *,
        idempotency_key: str | None = None,
    ) -> NovelOrchestrationCreateResult:
        try:
            project = self.novel_service.get_project(novel_id)
            plan = self.novel_service.get_novel_plan(novel_id)
            chapters = self.novel_service.list_chapter_plans(
                novel_id,
                limit=1000,
            )
        except NovelProjectNotFoundError as exc:
            raise NovelOrchestrationNotFoundError(str(exc)) from exc

        if project.user_id != payload.user_id:
            raise NovelOrchestrationConflictError(
                "user_id does not own the selected Novel Project."
            )
        if plan.is_stale:
            raise NovelOrchestrationConflictError(
                "Novel Plan is stale; refresh it before orchestration."
            )

        selected_arc_ids = set(payload.arc_ids)
        if selected_arc_ids:
            existing_arc_ids = {
                item.arc_id
                for item in self.novel_service.list_story_arcs(
                    novel_id,
                    limit=1000,
                )
            }
            missing = sorted(selected_arc_ids - existing_arc_ids)
            if missing:
                raise NovelOrchestrationNotFoundError(
                    "Story Arc not found: " + ", ".join(missing)
                )

        selected = [
            chapter
            for chapter in chapters
            if (
                not selected_arc_ids
                or chapter.arc_id in selected_arc_ids
            )
            and (
                payload.start_chapter_number is None
                or chapter.chapter_number >= payload.start_chapter_number
            )
            and (
                payload.end_chapter_number is None
                or chapter.chapter_number <= payload.end_chapter_number
            )
        ]
        selected.sort(key=lambda item: item.chapter_number)
        if not selected:
            raise NovelOrchestrationConflictError(
                "No Chapter Plans match the orchestration selection."
            )

        accepted = self._accepted_snapshot(novel_id)
        step_payloads: list[dict[str, Any]] = []
        for sequence_no, chapter in enumerate(selected, 1):
            arc = self.novel_service.get_story_arc(
                novel_id,
                chapter.arc_id,
            )
            validation_detail = NovelOrchestrationDetail(
                orchestration_id="validation",
                novel_id=novel_id,
                user_id=payload.user_id,
                status="ready",
                revision=1,
                current_sequence_no=sequence_no,
                total_chapters=len(selected),
                accepted_chapters=0,
                created_at="validation",
                updated_at="validation",
                selection={},
                workflow=payload.workflow,
                queue=payload.queue,
                steps=[
                    NovelOrchestrationStep(
                        orchestration_id="validation",
                        sequence_no=sequence_no,
                        chapter_plan_id=chapter.chapter_plan_id,
                        chapter_plan_revision=chapter.revision,
                        chapter_number=chapter.chapter_number,
                        chapter_title=chapter.title,
                        arc_id=chapter.arc_id,
                        arc_revision=arc.revision,
                        status="pending",
                        created_at="validation",
                        updated_at="validation",
                    )
                ],
            )
            self._validate_grounding(
                self._workflow_request(
                    validation_detail,
                    validation_detail.steps[0],
                )
            )

            prior = accepted.get(chapter.chapter_number)
            is_current_accepted = bool(
                prior
                and prior["accepted"].source_chapter_plan_id
                == chapter.chapter_plan_id
                and prior["accepted"].source_chapter_plan_revision
                == chapter.revision
            )
            step_payloads.append(
                {
                    "sequence_no": sequence_no,
                    "chapter_plan_id": chapter.chapter_plan_id,
                    "chapter_plan_revision": chapter.revision,
                    "chapter_number": chapter.chapter_number,
                    "chapter_title": chapter.title,
                    "arc_id": chapter.arc_id,
                    "arc_revision": arc.revision,
                    "status": (
                        "accepted" if is_current_accepted else "pending"
                    ),
                    "manuscript_chapter_id": (
                        prior["chapter"].manuscript_chapter_id
                        if is_current_accepted
                        else None
                    ),
                    "accepted_revision": (
                        prior["chapter"].accepted_revision
                        if is_current_accepted
                        else None
                    ),
                }
            )

        selection = {
            "arc_ids": payload.arc_ids,
            "start_chapter_number": payload.start_chapter_number,
            "end_chapter_number": payload.end_chapter_number,
            "novel_plan_revision": plan.revision,
        }
        detail, deduplicated = self.storage.create(
            novel_id=novel_id,
            user_id=payload.user_id,
            selection=selection,
            workflow_policy=payload.workflow,
            queue_policy=payload.queue,
            metadata=payload.metadata,
            steps=step_payloads,
            idempotency_key=idempotency_key,
        )
        if not deduplicated and detail.status == "ready":
            detail = self._enqueue_current(detail)
        return NovelOrchestrationCreateResult(
            orchestration=detail,
            deduplicated=deduplicated,
        )

    def get(
        self,
        novel_id: str,
        orchestration_id: str,
    ) -> NovelOrchestrationDetail:
        return self.storage.get(novel_id, orchestration_id)

    def list(
        self,
        novel_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NovelOrchestrationSummary]:
        try:
            self.novel_service.get_project(novel_id)
        except NovelProjectNotFoundError as exc:
            raise NovelOrchestrationNotFoundError(str(exc)) from exc
        return self.storage.list(novel_id, limit=limit, offset=offset)

    def _import_candidate(
        self,
        detail: NovelOrchestrationDetail,
        step: NovelOrchestrationStep,
    ) -> NovelOrchestrationDetail:
        existing = {
            item.chapter_number: item
            for item in self.manuscript_service.list_chapters(
                detail.novel_id,
                limit=1_000_000,
            )
        }.get(step.chapter_number)
        imported = self.manuscript_service.import_workflow_candidate(
            detail.novel_id,
            ManuscriptImportRequest(
                workflow_run_id=str(step.workflow_run_id),
                expected_manuscript_revision=(
                    existing.revision if existing is not None else None
                ),
            ),
        )
        approved = [
            item
            for item in imported.imported_revisions
            if item.source_workflow_run_id == step.workflow_run_id
            and item.review_status == "approved"
        ]
        if not approved:
            raise NovelOrchestrationConflictError(
                "Imported Workflow Run has no approved manuscript candidate."
            )
        return self.storage.mark_candidate(
            detail.novel_id,
            detail.orchestration_id,
            expected_revision=detail.revision,
            manuscript_chapter_id=(
                imported.chapter.manuscript_chapter_id
            ),
            candidate_revision=approved[-1].revision,
        )

    def advance(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        user_id: str | None = None,
    ) -> NovelOrchestrationDetail:
        detail = self.storage.get(novel_id, orchestration_id)
        self._assert_owner(detail, user_id)
        if detail.revision != expected_revision:
            raise NovelOrchestrationConflictError(
                "Novel Orchestration revision conflict: "
                f"expected={expected_revision}, current={detail.revision}."
            )

        for _ in range(4):
            if detail.status in {"completed", "failed", "paused"}:
                return detail
            if detail.status == "ready":
                return self._enqueue_current(detail)

            step = self._current_step(detail)
            if detail.status == "waiting_for_workflow":
                if not step.workflow_run_id:
                    return self.storage.mark_failed(
                        novel_id,
                        orchestration_id,
                        expected_revision=detail.revision,
                        error="Current chapter has no Workflow Run binding.",
                    )
                try:
                    control = self.workflow_queue.get_control(
                        step.workflow_run_id
                    )
                    run = self.workflow_queue.run_storage.get_run(
                        step.workflow_run_id
                    )
                except KeyError as exc:
                    return self.storage.mark_failed(
                        novel_id,
                        orchestration_id,
                        expected_revision=detail.revision,
                        error=str(exc),
                    )
                if control["queue_status"] in self.ACTIVE_QUEUE_STATUSES:
                    return detail
                if (
                    control["queue_status"] == "completed"
                    and run["execution_status"] == "succeeded"
                    and run["quality_gate_passed"]
                ):
                    try:
                        return self._import_candidate(detail, step)
                    except Exception as exc:
                        return self.storage.mark_failed(
                            novel_id,
                            orchestration_id,
                            expected_revision=detail.revision,
                            error=str(exc),
                        )
                error = (
                    run.get("error")
                    or control.get("last_error")
                    or (
                        "Workflow did not produce a completed, "
                        "quality-gate-passed candidate."
                    )
                )
                return self.storage.mark_failed(
                    novel_id,
                    orchestration_id,
                    expected_revision=detail.revision,
                    error=error,
                )

            if detail.status == "waiting_for_acceptance":
                if not step.manuscript_chapter_id:
                    return self.storage.mark_failed(
                        novel_id,
                        orchestration_id,
                        expected_revision=detail.revision,
                        error="Current chapter has no Manuscript candidate.",
                    )
                manuscript = self.manuscript_service.get_chapter(
                    novel_id,
                    step.manuscript_chapter_id,
                )
                accepted = manuscript.accepted
                if (
                    accepted is None
                    or accepted.revision != step.candidate_revision
                    or accepted.source_workflow_run_id
                    != step.workflow_run_id
                ):
                    return detail
                detail = self.storage.mark_accepted(
                    novel_id,
                    orchestration_id,
                    expected_revision=detail.revision,
                    accepted_revision=accepted.revision,
                )
                continue

        return detail

    def pause(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        user_id: str | None = None,
    ) -> NovelOrchestrationDetail:
        detail = self.storage.get(novel_id, orchestration_id)
        self._assert_owner(detail, user_id)
        return self.storage.pause(
            novel_id,
            orchestration_id,
            expected_revision=expected_revision,
        )

    def resume(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        user_id: str | None = None,
    ) -> NovelOrchestrationDetail:
        detail = self.storage.get(novel_id, orchestration_id)
        self._assert_owner(detail, user_id)
        resumed = self.storage.resume(
            novel_id,
            orchestration_id,
            expected_revision=expected_revision,
        )
        return self.advance(
            novel_id,
            orchestration_id,
            expected_revision=resumed.revision,
            user_id=user_id,
        )

    def retry(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        reset_attempts: bool = True,
        user_id: str | None = None,
    ) -> NovelOrchestrationDetail:
        detail = self.storage.get(novel_id, orchestration_id)
        self._assert_owner(detail, user_id)
        if detail.revision != expected_revision:
            raise NovelOrchestrationConflictError(
                "Novel Orchestration revision conflict: "
                f"expected={expected_revision}, current={detail.revision}."
            )
        if detail.status not in {"failed", "waiting_for_acceptance"}:
            raise NovelOrchestrationConflictError(
                "Only a failed or candidate-waiting Novel Orchestration "
                "can be retried."
            )
        step = self._current_step(detail)
        request = self._workflow_request(detail, step)
        self._validate_grounding(request)

        if detail.status == "waiting_for_acceptance":
            return self._enqueue_current(
                detail,
                retry=True,
                workflow_attempt=step.workflow_attempt + 1,
            )

        if step.workflow_run_id:
            try:
                control = self.workflow_queue.get_control(step.workflow_run_id)
                run = self.workflow_queue.run_storage.get_run(
                    step.workflow_run_id
                )
            except KeyError:
                control = None
                run = None
            if control and control["queue_status"] in {"failed", "dead_letter"}:
                self.workflow_queue.retry_run(
                    step.workflow_run_id,
                    reset_attempts=reset_attempts,
                )
                return self.storage.attach_workflow(
                    novel_id,
                    orchestration_id,
                    expected_revision=detail.revision,
                    workflow_run_id=step.workflow_run_id,
                    workflow_attempt=step.workflow_attempt + 1,
                    retry=True,
                )
            if (
                control
                and control["queue_status"] == "completed"
                and run
                and run["execution_status"] == "succeeded"
            ):
                return self.storage.attach_workflow(
                    novel_id,
                    orchestration_id,
                    expected_revision=detail.revision,
                    workflow_run_id=step.workflow_run_id,
                    workflow_attempt=step.workflow_attempt + 1,
                    retry=True,
                )
            if control and control["queue_status"] in self.ACTIVE_QUEUE_STATUSES:
                raise NovelOrchestrationConflictError(
                    "Current Workflow Run is still active."
                )

        return self._enqueue_current(
            detail,
            retry=True,
            workflow_attempt=step.workflow_attempt + 1,
        )
