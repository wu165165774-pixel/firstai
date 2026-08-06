from __future__ import annotations

import asyncio
import json
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace

from app.workflows.async_executor import (
    AsyncWorkflowExecutor,
)
from app.workflows.async_queue import (
    WorkflowAsyncQueue,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
)


def make_result(
    *,
    agent: str,
    content: str,
):
    return SimpleNamespace(
        agent=agent,
        success=True,
        content=content,
        provider="test",
        model="test-model",
        finish_reason="stop",
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
        latency_ms=5.0,
        metadata={
            "test": True,
        },
    )


def approved_review() -> str:

    return json.dumps(
        {
            "approved": True,
            "summary": "Approved.",
            "issues": [],
            "scores": {
                "continuity": 90,
                "character_consistency": 90,
                "world_consistency": 90,
                "plot_logic": 90,
                "prose_quality": 90,
                "pacing": 90,
                "overall": 90,
            },
        }
    )


class NeverCalledManager:

    def __init__(
        self,
    ) -> None:

        self.calls = 0

    async def execute(
        self,
        *,
        agent_name,
        context,
    ):

        _ = agent_name
        _ = context

        self.calls += 1

        raise AssertionError(
            "External API process must "
            "not execute workflow agents."
        )


class ApprovedManager:

    async def execute(
        self,
        *,
        agent_name,
        context,
    ):

        _ = context

        if agent_name == "chapter":

            return make_result(
                agent="chapter",
                content="Draft.",
            )

        if agent_name == "review":

            return make_result(
                agent="review",
                content=approved_review(),
            )

        raise AssertionError(
            agent_name
        )


class BlockingManager:

    def __init__(
        self,
    ) -> None:

        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(
        self,
        *,
        agent_name,
        context,
    ):

        _ = context

        if agent_name == "chapter":

            self.started.set()

            await self.release.wait()

            return make_result(
                agent="chapter",
                content="Blocked draft.",
            )

        if agent_name == "review":

            return make_result(
                agent="review",
                content=approved_review(),
            )

        raise AssertionError(
            agent_name
        )


class StandaloneWorkerTests(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(
        self,
    ) -> None:

        self.temp_dir = (
            tempfile
            .TemporaryDirectory()
        )

        self.db_path = str(
            Path(
                self.temp_dir.name
            )
            / "workflow_runs.db"
        )

    def tearDown(
        self,
    ) -> None:

        self.temp_dir.cleanup()

    def request(
        self,
    ) -> ChapterWorkflowRequest:

        return ChapterWorkflowRequest(
            user_id="user001",
            novel_id="novel001",
            instruction=(
                "Write a chapter."
            ),
            max_revision_rounds=0,
        )

    async def test_external_mode_only_enqueues(
        self,
    ) -> None:

        manager = NeverCalledManager()

        api_executor = (
            AsyncWorkflowExecutor(
                manager,
                db_path=self.db_path,
                execution_mode=(
                    "external"
                ),
                poll_interval=0.01,
            )
        )

        submitted = (
            await api_executor.submit(
                self.request()
            )
        )

        await asyncio.sleep(
            0.05
        )

        current = (
            api_executor
            .get_submission(
                submitted.run.run_id
            )
        )

        self.assertEqual(
            current.job.queue_status,
            "queued",
        )

        self.assertEqual(
            current.run.execution_status,
            "queued",
        )

        self.assertEqual(
            manager.calls,
            0,
        )

        self.assertEqual(
            api_executor.queue.list_workers(),
            [],
        )

        await api_executor.shutdown()

    async def test_worker_processes_external_job(
        self,
    ) -> None:

        api_executor = (
            AsyncWorkflowExecutor(
                NeverCalledManager(),
                db_path=self.db_path,
                execution_mode=(
                    "external"
                ),
                poll_interval=0.01,
            )
        )

        submitted = (
            await api_executor.submit(
                self.request()
            )
        )

        worker = AsyncWorkflowExecutor(
            ApprovedManager(),
            db_path=self.db_path,
            execution_mode="worker",
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.03,
        )

        worker.ensure_started(
            force=True
        )

        finished = (
            await api_executor
            .wait_for_terminal(
                submitted.run.run_id,
                timeout=3.0,
            )
        )

        self.assertEqual(
            finished.job.queue_status,
            "completed",
        )

        self.assertEqual(
            finished.run.execution_status,
            "succeeded",
        )

        workers = (
            worker.queue.list_workers(
                stale_after_seconds=1.0
            )
        )

        self.assertEqual(
            len(workers),
            1,
        )

        self.assertEqual(
            workers[0][
                "worker_status"
            ],
            "running",
        )

        await worker.shutdown()
        await api_executor.shutdown()

    async def test_cross_process_cancel(
        self,
    ) -> None:

        api_executor = (
            AsyncWorkflowExecutor(
                NeverCalledManager(),
                db_path=self.db_path,
                execution_mode=(
                    "external"
                ),
                poll_interval=0.01,
            )
        )

        manager = BlockingManager()

        worker = AsyncWorkflowExecutor(
            manager,
            db_path=self.db_path,
            execution_mode="worker",
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.03,
        )

        submitted = (
            await api_executor.submit(
                self.request()
            )
        )

        worker.ensure_started(
            force=True
        )

        await asyncio.wait_for(
            manager.started.wait(),
            timeout=2.0,
        )

        cancelling = (
            await api_executor.cancel(
                submitted.run.run_id
            )
        )

        self.assertIn(
            cancelling.job.queue_status,
            {
                "cancelling",
                "cancelled",
            },
        )

        finished = (
            await api_executor
            .wait_for_terminal(
                submitted.run.run_id,
                timeout=3.0,
            )
        )

        self.assertEqual(
            finished.job.queue_status,
            "cancelled",
        )

        self.assertEqual(
            finished.run.execution_status,
            "cancelled",
        )

        await worker.shutdown()
        await api_executor.shutdown()

    async def test_graceful_shutdown_requeues_run(
        self,
    ) -> None:

        api_executor = (
            AsyncWorkflowExecutor(
                NeverCalledManager(),
                db_path=self.db_path,
                execution_mode=(
                    "external"
                ),
                poll_interval=0.01,
            )
        )

        manager = BlockingManager()

        worker = AsyncWorkflowExecutor(
            manager,
            db_path=self.db_path,
            execution_mode="worker",
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.03,
        )

        submitted = (
            await api_executor.submit(
                self.request()
            )
        )

        worker.ensure_started(
            force=True
        )

        await asyncio.wait_for(
            manager.started.wait(),
            timeout=2.0,
        )

        await worker.shutdown()

        current = (
            api_executor
            .get_submission(
                submitted.run.run_id
            )
        )

        self.assertEqual(
            current.job.queue_status,
            "queued",
        )

        self.assertEqual(
            current.run.execution_status,
            "queued",
        )

        event_types = [
            event.event_type
            for event in (
                current.run.events
            )
        ]

        self.assertIn(
            "worker_released",
            event_types,
        )

        await api_executor.shutdown()

    async def test_two_workers_claim_distinct_jobs(
        self,
    ) -> None:

        queue = WorkflowAsyncQueue(
            self.db_path
        )

        first_run_id, _ = queue.enqueue(
            self.request()
        )

        second_run_id, _ = queue.enqueue(
            self.request()
        )

        first_claim = queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        second_claim = queue.claim_next(
            worker_id="worker-b",
            lease_seconds=1.0,
        )

        third_claim = queue.claim_next(
            worker_id="worker-c",
            lease_seconds=1.0,
        )

        self.assertIsNotNone(
            first_claim
        )

        self.assertIsNotNone(
            second_claim
        )

        self.assertIsNone(
            third_claim
        )

        claimed_ids = {
            first_claim[0],
            second_claim[0],
        }

        self.assertEqual(
            claimed_ids,
            {
                first_run_id,
                second_run_id,
            },
        )

    async def test_worker_registry_lifecycle(
        self,
    ) -> None:

        queue = WorkflowAsyncQueue(
            self.db_path
        )

        queue.register_worker(
            "worker-a",
            capacity=2,
            metadata={
                "container": "test"
            },
        )

        queue.heartbeat_worker(
            "worker-a",
            active_count=1,
        )

        running = queue.list_workers(
            stale_after_seconds=60.0
        )

        self.assertEqual(
            running[0][
                "worker_status"
            ],
            "running",
        )

        self.assertEqual(
            running[0][
                "active_count"
            ],
            1,
        )

        queue.mark_worker_stopping(
            "worker-a"
        )

        stopping = queue.list_workers(
            stale_after_seconds=60.0
        )

        self.assertEqual(
            stopping[0][
                "worker_status"
            ],
            "stopping",
        )

        queue.mark_worker_stopped(
            "worker-a"
        )

        stopped = queue.list_workers(
            stale_after_seconds=60.0
        )

        self.assertEqual(
            stopped[0][
                "worker_status"
            ],
            "stopped",
        )

        self.assertEqual(
            stopped[0][
                "active_count"
            ],
            0,
        )

    async def test_invalid_execution_mode(
        self,
    ) -> None:

        with self.assertRaises(
            ValueError
        ):

            AsyncWorkflowExecutor(
                NeverCalledManager(),
                db_path=self.db_path,
                execution_mode="invalid",
            )


class StandaloneWorkerOpenApiTests(
    unittest.TestCase
):

    def test_worker_route_registered(
        self,
    ) -> None:

        from app.main import app

        schema = app.openapi()

        paths = schema.get(
            "paths",
            {},
        )

        components = (
            schema
            .get("components", {})
            .get("schemas", {})
        )

        self.assertIn(
            (
                "/api/v1/workflows/"
                "workers"
            ),
            paths,
        )

        for name in (
            "WorkflowWorkerInfo",
            "WorkflowWorkerListResponse",
        ):

            self.assertIn(
                name,
                components,
            )

    def test_worker_entrypoint_imports(
        self,
    ) -> None:

        from app.workers.workflow_worker import (
            main,
            run_worker,
        )

        self.assertTrue(
            callable(main)
        )

        self.assertTrue(
            callable(run_worker)
        )
