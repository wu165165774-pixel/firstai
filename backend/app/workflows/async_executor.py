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
        poll_interval: float = 0.25,
    ) -> None:

        self._agent_manager = (
            agent_manager
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

        self._poll_interval = max(
            float(
                poll_interval
            ),
            0.01,
        )

        self._worker_id = (
            "worker-"
            + str(
                uuid.uuid4()
            )
        )

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

    def ensure_started(
        self,
    ) -> None:

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

    async def submit(
        self,
        request,
        *,
        idempotency_key: str | None = None,
    ) -> WorkflowAsyncSubmission:

        run_id, deduplicated = (
            self._queue.enqueue(
                request,
                idempotency_key=(
                    idempotency_key
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

    async def _worker_loop(
        self,
    ) -> None:

        try:

            while not self._stopping:

                self._queue.recover_stale()

                for run_id, task in list(
                    self._active.items()
                ):

                    if task.done():

                        self._active.pop(
                            run_id,
                            None,
                        )

                while (
                    len(
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

        except asyncio.CancelledError:

            return

    async def _execute(
        self,
        run_id: str,
        request,
    ) -> None:

        heartbeat_task = (
            asyncio.create_task(
                self._heartbeat_loop(
                    run_id
                )
            )
        )

        try:

            result = await ChapterWorkflow(
                self._agent_manager
            ).run(
                request
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

            self._queue.mark_terminal(
                run_id
            )

        except asyncio.CancelledError:

            self._queue.mark_cancelled(
                run_id,
                reason=(
                    "Cancelled by user."
                ),
            )

        except Exception as exc:

            self._queue.run_storage.fail_run(
                run_id,
                str(exc),
            )

            self._queue.mark_failed(
                run_id
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
