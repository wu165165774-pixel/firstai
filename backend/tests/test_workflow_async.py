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

        self.started = (
            asyncio.Event()
        )

        self.release = (
            asyncio.Event()
        )

        self.chapter_calls = 0

    async def execute(
        self,
        *,
        agent_name,
        context,
    ):

        _ = context

        if agent_name == "chapter":

            self.chapter_calls += 1
            self.started.set()

            await self.release.wait()

            return make_result(
                agent="chapter",
                content=(
                    "Blocked draft."
                ),
            )

        if agent_name == "review":

            return make_result(
                agent="review",
                content=approved_review(),
            )

        raise AssertionError(
            agent_name
        )


class AsyncWorkflowTests(
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

    async def test_submit_is_idempotent(
        self,
    ) -> None:

        manager = BlockingManager()

        executor = AsyncWorkflowExecutor(
            manager,
            execution_mode="embedded",
            db_path=self.db_path,
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.05,
        )

        first = await executor.submit(
            self.request(),
            idempotency_key=(
                "same-request"
            ),
        )

        second = await executor.submit(
            self.request(),
            idempotency_key=(
                "same-request"
            ),
        )

        self.assertEqual(
            first.run.run_id,
            second.run.run_id,
        )

        self.assertFalse(
            first.deduplicated
        )

        self.assertTrue(
            second.deduplicated
        )

        await executor.cancel(
            first.run.run_id
        )

        await executor.wait_for_terminal(
            first.run.run_id
        )

        await executor.shutdown()

    async def test_worker_executes_and_persists(
        self,
    ) -> None:

        executor = AsyncWorkflowExecutor(
            ApprovedManager(),
            execution_mode="embedded",
            db_path=self.db_path,
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.05,
        )

        submitted = await executor.submit(
            self.request()
        )

        finished = (
            await executor
            .wait_for_terminal(
                submitted.run.run_id
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

        event_types = [
            event.event_type
            for event in (
                finished.run.events
            )
        ]

        self.assertIn(
            "run_queued",
            event_types,
        )

        self.assertIn(
            "run_claimed",
            event_types,
        )

        self.assertIn(
            "run_completed",
            event_types,
        )

        await executor.shutdown()

    async def test_queued_job_can_cancel(
        self,
    ) -> None:

        queue = WorkflowAsyncQueue(
            self.db_path
        )

        run_id, _ = queue.enqueue(
            self.request()
        )

        control = queue.request_cancel(
            run_id
        )

        self.assertEqual(
            control["queue_status"],
            "cancelled",
        )

        run = (
            queue
            .run_storage
            .get_run(
                run_id
            )
        )

        self.assertEqual(
            run["execution_status"],
            "cancelled",
        )

    async def test_running_job_can_cancel(
        self,
    ) -> None:

        manager = BlockingManager()

        executor = AsyncWorkflowExecutor(
            manager,
            execution_mode="embedded",
            db_path=self.db_path,
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.05,
        )

        submitted = await executor.submit(
            self.request()
        )

        await asyncio.wait_for(
            manager.started.wait(),
            timeout=2.0,
        )

        cancelling = await executor.cancel(
            submitted.run.run_id
        )

        self.assertIn(
            cancelling.job.queue_status,
            {
                "cancelling",
                "cancelled",
            },
        )

        finished = (
            await executor
            .wait_for_terminal(
                submitted.run.run_id
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

        await executor.shutdown()

    async def test_stale_lease_is_recovered(
        self,
    ) -> None:

        queue = WorkflowAsyncQueue(
            self.db_path
        )

        run_id, _ = queue.enqueue(
            self.request()
        )

        claimed = queue.claim_next(
            worker_id="dead-worker",
            lease_seconds=0.05,
        )

        self.assertIsNotNone(
            claimed
        )

        await asyncio.sleep(
            0.08
        )

        recovered = (
            queue.recover_stale()
        )

        self.assertIn(
            run_id,
            recovered,
        )

        control = queue.get_control(
            run_id
        )

        self.assertEqual(
            control["queue_status"],
            "queued",
        )

        run = (
            queue
            .run_storage
            .get_run(
                run_id
            )
        )

        self.assertEqual(
            run["execution_status"],
            "queued",
        )

    async def test_concurrency_limit_is_one(
        self,
    ) -> None:

        manager = BlockingManager()

        executor = AsyncWorkflowExecutor(
            manager,
            execution_mode="embedded",
            db_path=self.db_path,
            max_concurrency=1,
            poll_interval=0.01,
            lease_seconds=1.0,
            heartbeat_seconds=0.05,
        )

        first = await executor.submit(
            self.request()
        )

        second = await executor.submit(
            self.request()
        )

        await asyncio.wait_for(
            manager.started.wait(),
            timeout=2.0,
        )

        await asyncio.sleep(
            0.05
        )

        first_control = (
            executor.queue.get_control(
                first.run.run_id
            )
        )

        second_control = (
            executor.queue.get_control(
                second.run.run_id
            )
        )

        self.assertEqual(
            first_control[
                "queue_status"
            ],
            "running",
        )

        self.assertEqual(
            second_control[
                "queue_status"
            ],
            "queued",
        )

        self.assertEqual(
            manager.chapter_calls,
            1,
        )

        manager.release.set()

        await executor.wait_for_terminal(
            first.run.run_id
        )

        await executor.wait_for_terminal(
            second.run.run_id
        )

        self.assertEqual(
            manager.chapter_calls,
            2,
        )

        await executor.shutdown()

    async def test_long_idempotency_key_rejected(
        self,
    ) -> None:

        queue = WorkflowAsyncQueue(
            self.db_path
        )

        with self.assertRaises(
            ValueError
        ):

            queue.enqueue(
                self.request(),
                idempotency_key=(
                    "x" * 129
                ),
            )


class AsyncWorkflowOpenApiTests(
    unittest.TestCase
):

    def test_async_routes_registered(
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
                "chapter/runs/async"
            ),
            paths,
        )

        self.assertIn(
            (
                "/api/v1/workflows/"
                "runs/{run_id}/control"
            ),
            paths,
        )

        self.assertIn(
            (
                "/api/v1/workflows/"
                "runs/{run_id}/cancel"
            ),
            paths,
        )

        for name in [
            "WorkflowJobControl",
            "WorkflowAsyncSubmission",
            (
                "WorkflowAsync"
                "SubmissionResponse"
            ),
        ]:

            self.assertIn(
                name,
                components,
            )
