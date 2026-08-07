from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace

from app.workflows.async_executor import (
    AsyncWorkflowExecutor,
)
from app.workflows.async_queue import (
    WorkflowAsyncQueue,
    WorkflowQueueFullError,
    WorkflowUserQuotaError,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
)


def make_result(*, agent: str, content: str):
    return SimpleNamespace(
        agent=agent,
        success=True,
        content=content,
        provider="test",
        model="test-model",
        finish_reason="stop",
        usage=SimpleNamespace(
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
        latency_ms=1.0,
        metadata={},
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


class SuccessManager:

    async def execute(self, *, agent_name, context):
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
        raise AssertionError(agent_name)


class SlowManager:

    async def execute(self, *, agent_name, context):
        _ = agent_name
        _ = context
        await asyncio.sleep(1.0)
        raise AssertionError("unreachable")


class WorkflowBackpressureTests(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp_dir.name)
            / "workflow_runs.db"
        )
        self.queue = WorkflowAsyncQueue(
            self.db_path
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(
        self,
        *,
        user_id: str = "user001",
        instruction: str = "Write.",
    ) -> ChapterWorkflowRequest:
        return ChapterWorkflowRequest(
            user_id=user_id,
            novel_id="novel001",
            instruction=instruction,
            max_revision_rounds=0,
        )

    async def test_global_queue_limit_rejects(self) -> None:
        self.queue.enqueue(
            self.request(instruction="First."),
            max_queued_jobs=1,
            max_active_per_user=0,
        )

        with self.assertRaises(
            WorkflowQueueFullError
        ):
            self.queue.enqueue(
                self.request(instruction="Second."),
                max_queued_jobs=1,
                max_active_per_user=0,
            )

        metrics = self.queue.queue_metrics(
            max_queued_jobs=1,
            max_active_per_user=0,
            default_timeout_seconds=10.0,
        )

        self.assertTrue(
            metrics["backpressure_active"]
        )
        self.assertEqual(
            metrics["queue_full_rejections"],
            1,
        )

    async def test_idempotency_bypasses_full_queue(self) -> None:
        run_id, deduplicated = self.queue.enqueue(
            self.request(),
            idempotency_key="same-key",
            max_queued_jobs=1,
            max_active_per_user=0,
        )
        repeated_id, repeated = self.queue.enqueue(
            self.request(),
            idempotency_key="same-key",
            max_queued_jobs=1,
            max_active_per_user=0,
        )
        self.assertFalse(deduplicated)
        self.assertTrue(repeated)
        self.assertEqual(run_id, repeated_id)

    async def test_user_active_quota_isolated_by_user(self) -> None:
        self.queue.enqueue(
            self.request(user_id="user-a"),
            max_queued_jobs=0,
            max_active_per_user=1,
        )

        with self.assertRaises(
            WorkflowUserQuotaError
        ):
            self.queue.enqueue(
                self.request(user_id="user-a"),
                max_queued_jobs=0,
                max_active_per_user=1,
            )

        run_id, _ = self.queue.enqueue(
            self.request(user_id="user-b"),
            max_queued_jobs=0,
            max_active_per_user=1,
        )
        self.assertTrue(run_id)

    async def test_timeout_policy_is_persisted(self) -> None:
        run_id, _ = self.queue.enqueue(
            self.request(),
            timeout_seconds=12.5,
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        control = self.queue.get_control(run_id)
        self.assertEqual(
            control["timeout_seconds"],
            12.5,
        )
        self.assertEqual(
            control["timed_out_count"],
            0,
        )

    async def test_timeout_validation(self) -> None:
        for value in (0.0, 86400.1):
            with self.assertRaises(ValueError):
                self.queue.enqueue(
                    self.request(),
                    timeout_seconds=value,
                    max_queued_jobs=0,
                    max_active_per_user=0,
                )

    async def test_executor_timeout_retries_then_dlq(self) -> None:
        executor = AsyncWorkflowExecutor(
            SlowManager(),
            db_path=self.db_path,
            execution_mode="embedded",
            max_concurrency=1,
            poll_interval=0.01,
            heartbeat_seconds=0.02,
            lease_seconds=0.2,
            max_queued_jobs=0,
            max_active_per_user=0,
            default_timeout_seconds=0.1,
        )
        try:
            submission = await executor.submit(
                self.request(),
                max_attempts=2,
                retry_base_seconds=0.01,
                timeout_seconds=0.1,
            )
            final = await executor.wait_for_terminal(
                submission.run.run_id,
                timeout=3.0,
            )
            self.assertEqual(
                final.job.queue_status,
                "dead_letter",
            )
            self.assertEqual(
                final.job.timed_out_count,
                2,
            )
            event_types = [
                event.event_type
                for event in final.run.events
            ]
            self.assertEqual(
                event_types.count(
                    "run_attempt_timed_out"
                ),
                2,
            )
            self.assertEqual(
                event_types.count(
                    "retry_scheduled"
                ),
                1,
            )
        finally:
            await executor.shutdown()

    async def test_worker_control_lifecycle(self) -> None:
        self.queue.register_worker(
            "worker-a",
            capacity=2,
        )
        paused = self.queue.set_worker_control(
            "worker-a",
            control_mode="paused",
        )
        self.assertFalse(
            paused["accepting_work"]
        )
        resumed = self.queue.set_worker_control(
            "worker-a",
            control_mode="running",
        )
        self.assertTrue(
            resumed["accepting_work"]
        )
        draining = self.queue.set_worker_control(
            "worker-a",
            control_mode="draining",
        )
        self.assertEqual(
            draining["control_mode"],
            "draining",
        )
        self.queue.heartbeat_worker(
            "worker-a",
            active_count=0,
        )
        drained = self.queue.get_worker_control(
            "worker-a"
        )
        self.assertEqual(
            drained["control_mode"],
            "paused",
        )

    async def test_worker_loop_respects_pause_resume(self) -> None:
        executor = AsyncWorkflowExecutor(
            SuccessManager(),
            db_path=self.db_path,
            execution_mode="embedded",
            poll_interval=0.01,
            heartbeat_seconds=0.02,
            lease_seconds=0.2,
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        executor.ensure_started()
        try:
            for _ in range(100):
                try:
                    executor.queue.get_worker_control(
                        executor.worker_id
                    )
                    break
                except KeyError:
                    await asyncio.sleep(0.01)
            executor.queue.set_worker_control(
                executor.worker_id,
                control_mode="paused",
            )
            submission = await executor.submit(
                self.request(),
            )
            await asyncio.sleep(0.1)
            queued = executor.get_submission(
                submission.run.run_id
            )
            self.assertEqual(
                queued.job.queue_status,
                "queued",
            )
            executor.queue.set_worker_control(
                executor.worker_id,
                control_mode="running",
            )
            final = await executor.wait_for_terminal(
                submission.run.run_id,
                timeout=3.0,
            )
            self.assertEqual(
                final.job.queue_status,
                "completed",
            )
        finally:
            await executor.shutdown()

    async def test_legacy_schema_migrates_d8_columns(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "ALTER TABLE workflow_run_jobs "
                "RENAME TO workflow_run_jobs_old"
            )
            conn.execute(
                """
                CREATE TABLE workflow_run_jobs (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    queue_status TEXT NOT NULL,
                    cancel_requested INTEGER
                        NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    heartbeat_at TEXT,
                    queued_at TEXT NOT NULL,
                    claimed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "DROP TABLE workflow_run_jobs_old"
            )
            conn.commit()

        WorkflowAsyncQueue(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            job_columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(workflow_run_jobs)"
                ).fetchall()
            }
            worker_columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(workflow_workers)"
                ).fetchall()
            }

        self.assertIn(
            "timeout_seconds",
            job_columns,
        )
        self.assertIn(
            "timed_out_count",
            job_columns,
        )
        self.assertIn(
            "control_mode",
            worker_columns,
        )


class WorkflowBackpressureOpenApiTests(
    unittest.TestCase
):

    def test_routes_headers_and_schemas(self) -> None:
        from app.main import app

        schema = app.openapi()
        paths = schema["paths"]

        submit = paths[
            "/api/v1/workflows/chapter/runs/async"
        ]["post"]

        parameter_names = {
            item["name"]
            for item in submit["parameters"]
        }

        self.assertIn(
            "X-Workflow-Timeout-Seconds",
            parameter_names,
        )

        for path in (
            "/api/v1/workflows/workers/{worker_id}/pause",
            "/api/v1/workflows/workers/{worker_id}/resume",
            "/api/v1/workflows/workers/{worker_id}/drain",
        ):
            self.assertIn(path, paths)

        components = schema["components"]["schemas"]
        self.assertIn(
            "WorkflowWorkerControlResponse",
            components,
        )
        self.assertIn(
            "timeout_seconds",
            components["WorkflowJobControl"][
                "properties"
            ],
        )


if __name__ == "__main__":
    unittest.main()
