from __future__ import annotations

import asyncio
import os
import uuid

from typing import Any

from app.workflows.async_queue import (
    WorkflowAsyncQueue,
)
from app.workflows.chapter_workflow import (
    ChapterWorkflow,
)
from app.workflows.grounding import (
    ChapterWorkflowGroundingService,
    chapter_workflow_grounding_service,
)
from app.workflows.run_schemas import (
    WorkflowAsyncSubmission,
    WorkflowJobControl,
    WorkflowRunDetail,
)


class AsyncWorkflowExecutor:
    """
    In-process asynchronous worker with
    SQLite queue, leases, heartbeats,
    cancellation, and stale-job recovery.
    """

    def __init__(
        self,
        agent_manager: Any,
        *,
        db_path: str | None = None,
        max_concurrency: int | None = None,
        lease_seconds: float | None = None,
        heartbeat_seconds: float | None = None,
        max_retry_delay_seconds: float
        | None = None,
        max_queued_jobs: int | None = None,
        max_active_per_user: int | None = None,
        default_timeout_seconds: float | None = None,
        poll_interval: float = 0.25,
        execution_mode: str | None = None,
        grounding_service: ChapterWorkflowGroundingService | None = None,
    ) -> None:

        self._agent_manager = (
            agent_manager
        )

        self._grounding_service = (
            grounding_service
            or chapter_workflow_grounding_service
        )

        self._queue = WorkflowAsyncQueue(
            db_path
        )

        configured_concurrency = (
            max_concurrency
            if max_concurrency is not None
            else int(
                os.getenv(
                    "NOVELFORGE_WORKFLOW_CONCURRENCY",
                    "1",
                )
            )
        )

        self._max_concurrency = max(
            int(
                configured_concurrency
            ),
            1,
        )

        self._lease_seconds = max(
            float(
                lease_seconds
                if lease_seconds
                is not None
                else os.getenv(
                    "NOVELFORGE_WORKFLOW_LEASE_SECONDS",
                    "60",
                )
            ),
            0.1,
        )

        default_heartbeat = min(
            self._lease_seconds / 3.0,
            10.0,
        )

        self._heartbeat_seconds = max(
            float(
                heartbeat_seconds
                if heartbeat_seconds
                is not None
                else os.getenv(
                    "NOVELFORGE_WORKFLOW_HEARTBEAT_SECONDS",
                    str(
                        default_heartbeat
                    ),
                )
            ),
            0.02,
        )

        self._max_retry_delay_seconds = max(
            float(
                max_retry_delay_seconds
                if max_retry_delay_seconds
                is not None
                else os.getenv(
                    (
                        "NOVELFORGE_WORKFLOW_"
                        "MAX_RETRY_DELAY_SECONDS"
                    ),
                    "300",
                )
            ),
            0.01,
        )

        self._max_queued_jobs = max(
            int(
                max_queued_jobs
                if max_queued_jobs is not None
                else os.getenv(
                    "NOVELFORGE_WORKFLOW_MAX_QUEUED_JOBS",
                    "1000",
                )
            ),
            0,
        )

        self._max_active_per_user = max(
            int(
                max_active_per_user
                if max_active_per_user is not None
                else os.getenv(
                    "NOVELFORGE_WORKFLOW_MAX_ACTIVE_PER_USER",
                    "8",
                )
            ),
            0,
        )

        self._default_timeout_seconds = (
            self._queue._normalize_timeout(
                default_timeout_seconds
                if default_timeout_seconds is not None
                else float(
                    os.getenv(
                        "NOVELFORGE_WORKFLOW_TIMEOUT_SECONDS",
                        "900",
                    )
                )
            )
        )

        self._poll_interval = max(
            float(
                poll_interval
            ),
            0.01,
        )

        mode = (
            execution_mode
            or os.getenv(
                "NOVELFORGE_WORKFLOW_EXECUTION_MODE",
                "embedded",
            )
        ).strip().lower()

        if mode not in {
            "embedded",
            "external",
            "worker",
        }:

            raise ValueError(
                "Workflow execution mode must "
                "be embedded, external, or worker."
            )

        self._execution_mode = mode

        self._worker_id = (
            "worker-"
            + str(
                uuid.uuid4()
            )
        )

        self._worker_registered = False

        self._loop_task: (
            asyncio.Task[Any]
            | None
        ) = None

        self._active: dict[
            str,
            asyncio.Task[Any],
        ] = {}

        self._stopping = False

    @property
    def queue(
        self,
    ) -> WorkflowAsyncQueue:

        return self._queue

    @property
    def execution_mode(
        self,
    ) -> str:

        return self._execution_mode

    @property
    def worker_id(
        self,
    ) -> str:

        return self._worker_id

    def ensure_started(
        self,
        *,
        force: bool = False,
    ) -> None:

        if (
            self._execution_mode
            == "external"
            and not force
        ):

            return

        if (
            self._loop_task is not None
            and not self._loop_task.done()
        ):

            return

        asyncio.get_running_loop()

        self._stopping = False

        self._loop_task = (
            asyncio.create_task(
                self._worker_loop(),
                name=(
                    "novelforge-workflow-worker"
                ),
            )
        )

    async def run_forever(
        self,
    ) -> None:

        self.ensure_started(
            force=True
        )

        if self._loop_task is None:

            raise RuntimeError(
                "Workflow worker did not start."
            )

        await self._loop_task

    async def submit(
        self,
        request,
        *,
        idempotency_key: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        retry_base_seconds: float = 2.0,
        timeout_seconds: float | None = None,
    ) -> WorkflowAsyncSubmission:

        run_id, deduplicated = (
            self._queue.enqueue(
                request,
                idempotency_key=(
                    idempotency_key
                ),
                priority=priority,
                max_attempts=(
                    max_attempts
                ),
                retry_base_seconds=(
                    retry_base_seconds
                ),
                timeout_seconds=(
                    self._default_timeout_seconds
                    if timeout_seconds is None
                    else timeout_seconds
                ),
                max_queued_jobs=(
                    self._max_queued_jobs
                ),
                max_active_per_user=(
                    self._max_active_per_user
                ),
            )
        )

        self.ensure_started()

        return self.get_submission(
            run_id,
            deduplicated=(
                deduplicated
            ),
        )

    def get_submission(
        self,
        run_id: str,
        *,
        deduplicated: bool = False,
    ) -> WorkflowAsyncSubmission:

        run = (
            WorkflowRunDetail
            .model_validate(
                self
                ._queue
                .run_storage
                .get_run(
                    run_id
                )
            )
        )

        control = (
            WorkflowJobControl
            .model_validate(
                self
                ._queue
                .get_control(
                    run_id
                )
            )
        )

        return WorkflowAsyncSubmission(
            run=run,
            job=control,
            deduplicated=(
                deduplicated
            ),
        )

    async def cancel(
        self,
        run_id: str,
    ) -> WorkflowAsyncSubmission:

        control = (
            self._queue.request_cancel(
                run_id
            )
        )

        if (
            control["queue_status"]
            == "cancelling"
        ):

            task = self._active.get(
                run_id
            )

            if task is not None:

                task.cancel()

        self.ensure_started()

        return self.get_submission(
            run_id
        )

    async def retry(
        self,
        run_id: str,
        *,
        reset_attempts: bool = True,
        priority: int | None = None,
        max_attempts: int | None = None,
        retry_base_seconds: float
        | None = None,
        timeout_seconds: float
        | None = None,
    ) -> WorkflowAsyncSubmission:

        self._queue.retry_run(
            run_id,
            reset_attempts=(
                reset_attempts
            ),
            priority=priority,
            max_attempts=(
                max_attempts
            ),
            retry_base_seconds=(
                retry_base_seconds
            ),
            timeout_seconds=(
                timeout_seconds
            ),
        )

        self.ensure_started()

        return self.get_submission(
            run_id
        )

    async def wait_for_terminal(
        self,
        run_id: str,
        *,
        timeout: float = 10.0,
    ) -> WorkflowAsyncSubmission:

        deadline = (
            asyncio
            .get_running_loop()
            .time()
            + timeout
        )

        while True:

            submission = (
                self.get_submission(
                    run_id
                )
            )

            if (
                submission
                .job
                .queue_status
                in {
                    "cancelled",
                    "completed",
                    "failed",
                    "dead_letter",
                }
            ):

                return submission

            if (
                asyncio
                .get_running_loop()
                .time()
                >= deadline
            ):

                raise TimeoutError(
                    f"Workflow run did not "
                    f"finish: {run_id}"
                )

            await asyncio.sleep(
                self._poll_interval
            )

    async def shutdown(
        self,
    ) -> None:

        self._stopping = True

        if self._worker_registered:

            self._queue.mark_worker_stopping(
                self._worker_id
            )

        if self._loop_task is not None:

            self._loop_task.cancel()

        for task in list(
            self._active.values()
        ):

            task.cancel()

        tasks = [
            task
            for task in (
                [
                    self._loop_task
                ]
                + list(
                    self._active.values()
                )
            )
            if task is not None
        ]

        if tasks:

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        self._active.clear()

        self._loop_task = None

        if self._worker_registered:

            self._queue.mark_worker_stopped(
                self._worker_id
            )

            self._worker_registered = False

    async def _worker_loop(
        self,
    ) -> None:

        self._queue.register_worker(
            self._worker_id,
            capacity=self._max_concurrency,
            metadata={
                "execution_mode": (
                    self._execution_mode
                ),
                "process_id": os.getpid(),
            },
        )

        self._worker_registered = True

        try:

            while not self._stopping:

                self._queue.heartbeat_worker(
                    self._worker_id,
                    active_count=len(
                        self._active
                    ),
                )

                self._queue.recover_stale()

                worker_control = (
                    self._queue.get_worker_control(
                        self._worker_id
                    )
                )

                accepting_work = bool(
                    worker_control[
                        "accepting_work"
                    ]
                )

                for run_id, task in list(
                    self._active.items()
                ):

                    if task.done():

                        self._active.pop(
                            run_id,
                            None,
                        )

                while (
                    accepting_work
                    and len(
                        self._active
                    )
                    < self._max_concurrency
                ):

                    claimed = (
                        self._queue.claim_next(
                            worker_id=(
                                self._worker_id
                            ),
                            lease_seconds=(
                                self
                                ._lease_seconds
                            ),
                        )
                    )

                    if claimed is None:

                        break

                    run_id, request = claimed

                    task = asyncio.create_task(
                        self._execute(
                            run_id,
                            request,
                        ),
                        name=(
                            "workflow-run-"
                            + run_id
                        ),
                    )

                    self._active[
                        run_id
                    ] = task

                await asyncio.sleep(
                    self._poll_interval
                )

        except asyncio.CancelledError:

            return

    async def _heartbeat_loop(
        self,
        run_id: str,
        execution_task: asyncio.Task[Any],
    ) -> None:

        try:

            while True:

                await asyncio.sleep(
                    self
                    ._heartbeat_seconds
                )

                alive = (
                    self._queue.heartbeat(
                        run_id,
                        worker_id=(
                            self._worker_id
                        ),
                        lease_seconds=(
                            self
                            ._lease_seconds
                        ),
                    )
                )

                if not alive:

                    return

                if (
                    self
                    ._queue
                    .is_cancel_requested(
                        run_id
                    )
                ):

                    execution_task.cancel()

                    return

        except asyncio.CancelledError:

            return

    async def _execute(
        self,
        run_id: str,
        request,
    ) -> None:

        execution_task = (
            asyncio.current_task()
        )

        if execution_task is None:

            raise RuntimeError(
                "Workflow execution task "
                "is not available."
            )

        heartbeat_task = (
            asyncio.create_task(
                self._heartbeat_loop(
                    run_id,
                    execution_task,
                )
            )
        )

        try:

            control = self._queue.get_control(
                run_id
            )

            timeout_seconds = float(
                control["timeout_seconds"]
            )

            result = await asyncio.wait_for(
                ChapterWorkflow(
                    self._agent_manager,
                    grounding_service=self._grounding_service,
                ).run(
                    request
                ),
                timeout=timeout_seconds,
            )

            if (
                self
                ._queue
                .is_cancel_requested(
                    run_id
                )
            ):

                self._queue.mark_cancelled(
                    run_id,
                    reason=(
                        "Cancellation requested."
                    ),
                )

                return

            self._queue.run_storage.finalize_run(
                run_id,
                result,
            )

            persisted_run = (
                self
                ._queue
                .run_storage
                .get_run(
                    run_id
                )
            )

            if (
                persisted_run[
                    "execution_status"
                ]
                == "failed"
            ):

                self._queue.handle_failure(
                    run_id,
                    worker_id=(
                        self._worker_id
                    ),
                    error=(
                        persisted_run.get(
                            "error"
                        )
                        or (
                            "Workflow execution "
                            "failed."
                        )
                    ),
                    max_retry_delay_seconds=(
                        self
                        ._max_retry_delay_seconds
                    ),
                )

                return

            self._queue.mark_terminal(
                run_id
            )

        except TimeoutError:

            error = (
                "Workflow attempt timed out "
                f"after {timeout_seconds:g} seconds."
            )

            self._queue.record_timeout(
                run_id,
                worker_id=self._worker_id,
                error=error,
            )

            self._queue.handle_failure(
                run_id,
                worker_id=self._worker_id,
                error=error,
                max_retry_delay_seconds=(
                    self._max_retry_delay_seconds
                ),
            )

        except asyncio.CancelledError:

            if (
                self
                ._queue
                .is_cancel_requested(
                    run_id
                )
            ):

                self._queue.mark_cancelled(
                    run_id,
                    reason=(
                        "Cancelled by user."
                    ),
                )

            else:

                self._queue.release_claim(
                    run_id,
                    worker_id=(
                        self._worker_id
                    ),
                    reason=(
                        "Worker stopped before "
                        "the run completed."
                    ),
                )

        except Exception as exc:

            self._queue.handle_failure(
                run_id,
                worker_id=(
                    self._worker_id
                ),
                error=str(exc),
                max_retry_delay_seconds=(
                    self
                    ._max_retry_delay_seconds
                ),
            )

        finally:

            heartbeat_task.cancel()

            await asyncio.gather(
                heartbeat_task,
                return_exceptions=True,
            )

            self._active.pop(
                run_id,
                None,
            )
