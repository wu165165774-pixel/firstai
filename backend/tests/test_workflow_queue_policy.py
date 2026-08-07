from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest

from datetime import datetime
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


class FailOnceManager:

    def __init__(
        self,
    ) -> None:

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

            if self.chapter_calls == 1:

                raise RuntimeError(
                    "Temporary provider failure."
                )

            return make_result(
                agent="chapter",
                content="Recovered draft.",
            )

        if agent_name == "review":

            return make_result(
                agent="review",
                content=approved_review(),
            )

        raise AssertionError(
            agent_name
        )


class AlwaysFailManager:

    async def execute(
        self,
        *,
        agent_name,
        context,
    ):

        _ = agent_name
        _ = context

        raise RuntimeError(
            "Persistent provider failure."
        )


class WorkflowQueuePolicyTests(
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

        self.queue = WorkflowAsyncQueue(
            self.db_path
        )

    def tearDown(
        self,
    ) -> None:

        self.temp_dir.cleanup()

    def request(
        self,
        *,
        instruction: str = "Write a chapter.",
    ) -> ChapterWorkflowRequest:

        return ChapterWorkflowRequest(
            user_id="user001",
            novel_id="novel001",
            instruction=instruction,
            max_revision_rounds=0,
        )


    async def test_legacy_queue_schema_migrates_before_schedule_index(
        self,
    ) -> None:

        legacy_path = str(
            Path(
                self.temp_dir.name
            )
            / "legacy_workflow_runs.db"
        )

        with sqlite3.connect(
            legacy_path
        ) as conn:

            conn.executescript(
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
                );

                CREATE INDEX
                idx_workflow_jobs_status
                ON workflow_run_jobs(
                    queue_status,
                    queued_at
                );

                CREATE INDEX
                idx_workflow_jobs_lease
                ON workflow_run_jobs(
                    queue_status,
                    lease_expires_at
                );
                """
            )

            conn.commit()

        WorkflowAsyncQueue(
            legacy_path
        )

        with sqlite3.connect(
            legacy_path
        ) as conn:

            columns = {
                row[1]
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        workflow_run_jobs
                    )
                    """
                ).fetchall()
            }

            indexes = {
                row[1]
                for row in conn.execute(
                    """
                    PRAGMA index_list(
                        workflow_run_jobs
                    )
                    """
                ).fetchall()
            }

            migrated_row = conn.execute(
                """
                SELECT
                    priority,
                    attempt_count,
                    max_attempts,
                    retry_base_seconds,
                    available_at,
                    last_error,
                    dead_lettered_at
                FROM workflow_run_jobs
                LIMIT 1
                """
            ).fetchone()

        for column_name in (
            "priority",
            "attempt_count",
            "max_attempts",
            "retry_base_seconds",
            "available_at",
            "last_error",
            "dead_lettered_at",
        ):

            self.assertIn(
                column_name,
                columns,
            )

        self.assertIn(
            "idx_workflow_jobs_schedule",
            indexes,
        )

        self.assertIsNone(
            migrated_row
        )

    async def test_priority_claims_highest_first(
        self,
    ) -> None:

        low_id, _ = self.queue.enqueue(
            self.request(
                instruction="Low."
            ),
            priority=-10,
        )

        high_id, _ = self.queue.enqueue(
            self.request(
                instruction="High."
            ),
            priority=80,
        )

        claimed = self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        self.assertIsNotNone(
            claimed
        )

        self.assertEqual(
            claimed[0],
            high_id,
        )

        self.assertNotEqual(
            claimed[0],
            low_id,
        )

    async def test_same_priority_is_fifo(
        self,
    ) -> None:

        first_id, _ = self.queue.enqueue(
            self.request(
                instruction="First."
            ),
            priority=20,
        )

        second_id, _ = self.queue.enqueue(
            self.request(
                instruction="Second."
            ),
            priority=20,
        )

        first_claim = self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        second_claim = self.queue.claim_next(
            worker_id="worker-b",
            lease_seconds=1.0,
        )

        self.assertEqual(
            first_claim[0],
            first_id,
        )

        self.assertEqual(
            second_claim[0],
            second_id,
        )

    async def test_retry_uses_exponential_delay(
        self,
    ) -> None:

        run_id, _ = self.queue.enqueue(
            self.request(),
            max_attempts=3,
            retry_base_seconds=0.05,
        )

        first_claim = self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        self.assertEqual(
            first_claim[0],
            run_id,
        )

        first_retry = (
            self.queue.handle_failure(
                run_id,
                worker_id="worker-a",
                error="first",
                max_retry_delay_seconds=1.0,
            )
        )

        first_delay = (
            datetime.fromisoformat(
                first_retry["available_at"]
            )
            - datetime.fromisoformat(
                first_retry["updated_at"]
            )
        ).total_seconds()

        self.assertEqual(
            first_retry["queue_status"],
            "retry_wait",
        )

        self.assertGreaterEqual(
            first_delay,
            0.04,
        )

        await asyncio.sleep(
            0.07
        )

        second_claim = self.queue.claim_next(
            worker_id="worker-b",
            lease_seconds=1.0,
        )

        self.assertEqual(
            second_claim[0],
            run_id,
        )

        second_retry = (
            self.queue.handle_failure(
                run_id,
                worker_id="worker-b",
                error="second",
                max_retry_delay_seconds=1.0,
            )
        )

        second_delay = (
            datetime.fromisoformat(
                second_retry["available_at"]
            )
            - datetime.fromisoformat(
                second_retry["updated_at"]
            )
        ).total_seconds()

        self.assertGreaterEqual(
            second_delay,
            0.09,
        )

        self.assertGreater(
            second_delay,
            first_delay,
        )

    async def test_exhausted_run_enters_dead_letter(
        self,
    ) -> None:

        run_id, _ = self.queue.enqueue(
            self.request(),
            max_attempts=1,
            retry_base_seconds=0.01,
        )

        self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        control = (
            self.queue.handle_failure(
                run_id,
                worker_id="worker-a",
                error="permanent",
            )
        )

        self.assertEqual(
            control["queue_status"],
            "dead_letter",
        )

        self.assertEqual(
            control["attempt_count"],
            1,
        )

        self.assertEqual(
            control["last_error"],
            "permanent",
        )

        self.assertIsNotNone(
            control["dead_lettered_at"]
        )

        run = (
            self.queue
            .run_storage
            .get_run(
                run_id
            )
        )

        self.assertEqual(
            run["execution_status"],
            "dead_letter",
        )

        event_types = [
            event["event_type"]
            for event in run["events"]
        ]

        self.assertIn(
            "run_dead_lettered",
            event_types,
        )

    async def test_manual_retry_resets_dead_letter(
        self,
    ) -> None:

        run_id, _ = self.queue.enqueue(
            self.request(),
            priority=10,
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        self.queue.handle_failure(
            run_id,
            worker_id="worker-a",
            error="permanent",
        )

        control = self.queue.retry_run(
            run_id,
            reset_attempts=True,
            priority=90,
            max_attempts=4,
            retry_base_seconds=0.2,
        )

        self.assertEqual(
            control["queue_status"],
            "queued",
        )

        self.assertEqual(
            control["attempt_count"],
            0,
        )

        self.assertEqual(
            control["priority"],
            90,
        )

        self.assertEqual(
            control["max_attempts"],
            4,
        )

        self.assertEqual(
            control["retry_base_seconds"],
            0.2,
        )

        self.assertIsNone(
            control["last_error"]
        )

        self.assertIsNone(
            control["dead_lettered_at"]
        )

    async def test_retry_wait_can_cancel(
        self,
    ) -> None:

        run_id, _ = self.queue.enqueue(
            self.request(),
            max_attempts=2,
            retry_base_seconds=30.0,
        )

        self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        self.queue.handle_failure(
            run_id,
            worker_id="worker-a",
            error="temporary",
        )

        cancelled = (
            self.queue.request_cancel(
                run_id
            )
        )

        self.assertEqual(
            cancelled["queue_status"],
            "cancelled",
        )

        self.assertTrue(
            cancelled["cancel_requested"]
        )

    async def test_metrics_and_dead_letter_list(
        self,
    ) -> None:

        self.queue.enqueue(
            self.request(
                instruction="Normal."
            ),
            priority=0,
        )

        self.queue.enqueue(
            self.request(
                instruction="Urgent."
            ),
            priority=100,
        )

        dead_id, _ = self.queue.enqueue(
            self.request(
                instruction="Fail."
            ),
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        self.queue.claim_next(
            worker_id="worker-b",
            lease_seconds=1.0,
        )

        claimed = self.queue.claim_next(
            worker_id="worker-c",
            lease_seconds=1.0,
        )

        self.assertEqual(
            claimed[0],
            dead_id,
        )

        self.queue.handle_failure(
            dead_id,
            worker_id="worker-c",
            error="dead",
        )

        metrics = (
            self.queue.queue_metrics()
        )

        self.assertEqual(
            metrics["total_jobs"],
            3,
        )

        self.assertEqual(
            metrics["dead_letter_count"],
            1,
        )

        dead_letters = (
            self.queue.list_dead_letters()
        )

        self.assertEqual(
            len(dead_letters),
            1,
        )

        self.assertEqual(
            dead_letters[0]["run_id"],
            dead_id,
        )


    async def test_terminal_jobs_keep_priority_metrics(
        self,
    ) -> None:

        high_id, _ = self.queue.enqueue(
            self.request(
                instruction="High."
            ),
            priority=95,
            max_attempts=1,
        )

        low_id, _ = self.queue.enqueue(
            self.request(
                instruction="Low."
            ),
            priority=-50,
            max_attempts=1,
        )

        high_claim = self.queue.claim_next(
            worker_id="worker-a",
            lease_seconds=1.0,
        )

        self.assertEqual(
            high_claim[0],
            high_id,
        )

        self.queue.handle_failure(
            high_id,
            worker_id="worker-a",
            error="high failed",
        )

        low_claim = self.queue.claim_next(
            worker_id="worker-b",
            lease_seconds=1.0,
        )

        self.assertEqual(
            low_claim[0],
            low_id,
        )

        self.queue.handle_failure(
            low_id,
            worker_id="worker-b",
            error="low failed",
        )

        metrics = (
            self.queue.queue_metrics()
        )

        self.assertEqual(
            metrics["dead_letter_count"],
            2,
        )

        self.assertEqual(
            metrics["priority_min"],
            -50,
        )

        self.assertEqual(
            metrics["priority_max"],
            95,
        )

        self.assertEqual(
            metrics["priority_average"],
            22.5,
        )

    async def test_policy_validation(
        self,
    ) -> None:

        with self.assertRaises(
            ValueError
        ):

            self.queue.enqueue(
                self.request(),
                priority=101,
            )

        with self.assertRaises(
            ValueError
        ):

            self.queue.enqueue(
                self.request(),
                max_attempts=0,
            )

        with self.assertRaises(
            ValueError
        ):

            self.queue.enqueue(
                self.request(),
                retry_base_seconds=0.0,
            )

    async def test_executor_retries_then_succeeds(
        self,
    ) -> None:

        manager = FailOnceManager()

        executor = AsyncWorkflowExecutor(
            manager,
            db_path=self.db_path,
            execution_mode="embedded",
            poll_interval=0.005,
            lease_seconds=1.0,
            heartbeat_seconds=0.02,
            max_retry_delay_seconds=0.05,
        )

        submitted = await executor.submit(
            self.request(),
            priority=50,
            max_attempts=2,
            retry_base_seconds=0.01,
        )

        finished = (
            await executor
            .wait_for_terminal(
                submitted.run.run_id,
                timeout=5.0,
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

        self.assertEqual(
            finished.job.attempt_count,
            2,
        )

        event_types = [
            event.event_type
            for event in (
                finished.run.events
            )
        ]

        self.assertEqual(
            event_types.count(
                "retry_scheduled"
            ),
            1,
        )

        self.assertEqual(
            event_types.count(
                "run_claimed"
            ),
            2,
        )

        self.assertEqual(
            manager.chapter_calls,
            2,
        )

        await executor.shutdown()

    async def test_executor_dead_letters(
        self,
    ) -> None:

        executor = AsyncWorkflowExecutor(
            AlwaysFailManager(),
            db_path=self.db_path,
            execution_mode="embedded",
            poll_interval=0.005,
            lease_seconds=1.0,
            heartbeat_seconds=0.02,
            max_retry_delay_seconds=0.05,
        )

        submitted = await executor.submit(
            self.request(),
            max_attempts=2,
            retry_base_seconds=0.01,
        )

        finished = (
            await executor
            .wait_for_terminal(
                submitted.run.run_id,
                timeout=5.0,
            )
        )

        self.assertEqual(
            finished.job.queue_status,
            "dead_letter",
        )

        self.assertEqual(
            finished.run.execution_status,
            "dead_letter",
        )

        self.assertEqual(
            finished.job.attempt_count,
            2,
        )

        event_types = [
            event.event_type
            for event in (
                finished.run.events
            )
        ]

        self.assertEqual(
            event_types.count(
                "retry_scheduled"
            ),
            1,
        )

        self.assertEqual(
            event_types.count(
                "run_dead_lettered"
            ),
            1,
        )

        await executor.shutdown()


class WorkflowQueuePolicyOpenApiTests(
    unittest.TestCase
):

    def test_policy_routes_and_schemas(
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

        for path in (
            (
                "/api/v1/workflows/"
                "runs/{run_id}/retry"
            ),
            (
                "/api/v1/workflows/"
                "queue/metrics"
            ),
            (
                "/api/v1/workflows/"
                "dead-letter"
            ),
        ):

            self.assertIn(
                path,
                paths,
            )

        for name in (
            "WorkflowQueueRetryRequest",
            "WorkflowQueueMetrics",
            "WorkflowQueueMetricsResponse",
            "WorkflowDeadLetterEntry",
            "WorkflowDeadLetterListResponse",
        ):

            self.assertIn(
                name,
                components,
            )

        async_operation = (
            paths[
                (
                    "/api/v1/workflows/"
                    "chapter/runs/async"
                )
            ]["post"]
        )

        parameter_names = {
            parameter.get("name")
            for parameter in (
                async_operation.get(
                    "parameters",
                    []
                )
            )
        }

        for header_name in (
            "Idempotency-Key",
            "X-Workflow-Priority",
            "X-Workflow-Max-Attempts",
            (
                "X-Workflow-"
                "Retry-Base-Seconds"
            ),
        ):

            self.assertIn(
                header_name,
                parameter_names,
            )
