from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from app.workflows.async_queue import WorkflowAsyncQueue
from app.workflows.schemas import ChapterWorkflowRequest


class WorkflowOperationsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp_dir.name)
            / "workflow_runs.db"
        )
        self.queue = WorkflowAsyncQueue(self.db_path)

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

    def dead_letter(
        self,
        *,
        user_id: str = "user001",
    ) -> str:
        run_id, _ = self.queue.enqueue(
            self.request(user_id=user_id),
            max_attempts=1,
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        worker_id = "worker-" + run_id
        claimed = self.queue.claim_next(
            worker_id=worker_id,
            lease_seconds=5.0,
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed[0], run_id)
        self.queue.handle_failure(
            run_id,
            worker_id=worker_id,
            error="forced failure",
        )
        return run_id

    def test_single_retry_can_override_timeout(self) -> None:
        run_id = self.dead_letter()
        self.queue.retry_run(
            run_id,
            timeout_seconds=12.5,
        )
        control = self.queue.get_control(run_id)
        self.assertEqual(control["queue_status"], "queued")
        self.assertEqual(control["timeout_seconds"], 12.5)

    def test_bulk_replay_requeues_explicit_dead_letters(self) -> None:
        first = self.dead_letter(user_id="user-a")
        second = self.dead_letter(user_id="user-b")
        result = self.queue.replay_dead_letters(
            [first, second],
            timeout_seconds=15.0,
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        self.assertEqual(result["requested_count"], 2)
        self.assertEqual(result["replayed_count"], 2)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["replayed_run_ids"], [first, second])
        self.assertEqual(self.queue.get_control(first)["queue_status"], "queued")
        self.assertEqual(self.queue.get_control(second)["timeout_seconds"], 15.0)
        metrics = self.queue.queue_metrics(window_seconds=60.0)
        self.assertEqual(metrics["dlq_replayed_total"], 2)

    def test_bulk_replay_skips_missing_and_non_dlq(self) -> None:
        queued, _ = self.queue.enqueue(
            self.request(),
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        result = self.queue.replay_dead_letters(
            [queued, "missing-run"],
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        self.assertEqual(result["replayed_count"], 0)
        self.assertEqual(result["skipped_count"], 2)
        reasons = {item["reason"] for item in result["skipped"]}
        self.assertEqual(reasons, {"not_dead_letter", "not_found"})

    def test_bulk_replay_respects_queue_limit(self) -> None:
        dead = self.dead_letter(user_id="user-dead")
        self.queue.enqueue(
            self.request(user_id="user-waiting"),
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        result = self.queue.replay_dead_letters(
            [dead],
            max_queued_jobs=1,
            max_active_per_user=0,
        )
        self.assertEqual(result["replayed_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "queue_full")
        self.assertEqual(self.queue.get_control(dead)["queue_status"], "dead_letter")

    def test_archive_dry_run_then_execute_preserves_run(self) -> None:
        run_id, _ = self.queue.enqueue(
            self.request(),
            max_queued_jobs=0,
            max_active_per_user=0,
        )
        self.queue.request_cancel(run_id)
        preview = self.queue.archive_terminal_jobs(
            older_than_seconds=0.0,
            dry_run=True,
        )
        self.assertIn(run_id, preview["run_ids"])
        self.assertEqual(preview["archived_count"], 0)
        executed = self.queue.archive_terminal_jobs(
            older_than_seconds=0.0,
            dry_run=False,
        )
        self.assertEqual(executed["archived_count"], 1)
        with self.assertRaises(KeyError):
            self.queue.get_control(run_id)
        persisted = self.queue.run_storage.get_run(run_id)
        self.assertEqual(persisted["run_id"], run_id)
        event_types = [item["event_type"] for item in persisted["events"]]
        self.assertIn("queue_job_archived", event_types)
        archived = self.queue.list_archived_jobs()
        self.assertEqual(archived[0]["run_id"], run_id)

    def test_archive_excludes_dead_letter_by_default(self) -> None:
        run_id = self.dead_letter()
        default_result = self.queue.archive_terminal_jobs(
            older_than_seconds=0.0,
            include_dead_letter=False,
            dry_run=False,
        )
        self.assertEqual(default_result["archived_count"], 0)
        explicit = self.queue.archive_terminal_jobs(
            older_than_seconds=0.0,
            include_dead_letter=True,
            dry_run=False,
        )
        self.assertEqual(explicit["archived_count"], 1)
        self.assertEqual(explicit["run_ids"], [run_id])

    def test_metrics_report_operational_observability(self) -> None:
        run_id = self.dead_letter()
        metrics = self.queue.queue_metrics(window_seconds=3600.0)
        self.assertGreaterEqual(metrics["terminal_in_window"], 1)
        self.assertGreater(metrics["throughput_per_minute"], 0.0)
        self.assertGreaterEqual(metrics["queue_latency_samples"], 1)
        self.assertIsNotNone(metrics["queue_latency_seconds_average"])
        self.assertGreaterEqual(metrics["dead_lettered_in_window"], 1)
        self.assertEqual(self.queue.get_control(run_id)["queue_status"], "dead_letter")

    def test_worker_cluster_health(self) -> None:
        empty = self.queue.worker_cluster_health(stale_after_seconds=10.0)
        self.assertEqual(empty["health_status"], "unavailable")
        self.queue.register_worker("worker-a", capacity=2)
        healthy = self.queue.worker_cluster_health(stale_after_seconds=10.0)
        self.assertEqual(healthy["health_status"], "healthy")
        self.assertEqual(healthy["accepting_workers"], 1)
        self.queue.set_worker_control("worker-a", control_mode="paused")
        degraded = self.queue.worker_cluster_health(stale_after_seconds=10.0)
        self.assertEqual(degraded["health_status"], "degraded")
        self.assertEqual(degraded["accepting_workers"], 0)

    def test_stale_worker_history_does_not_degrade_live_cluster(self) -> None:
        import sqlite3

        self.queue.register_worker(
            "worker-stale",
            capacity=1,
        )

        with sqlite3.connect(
            self.db_path
        ) as conn:
            conn.execute(
                """
                UPDATE workflow_workers
                SET heartbeat_at = ?
                WHERE worker_id = ?
                """,
                (
                    "2000-01-01T00:00:00+00:00",
                    "worker-stale",
                ),
            )
            conn.commit()

        self.queue.register_worker(
            "worker-live",
            capacity=1,
        )

        health = self.queue.worker_cluster_health(
            stale_after_seconds=10.0
        )

        self.assertEqual(
            health["stale_workers"],
            1,
        )
        self.assertEqual(
            health["running_workers"],
            1,
        )
        self.assertEqual(
            health["accepting_workers"],
            1,
        )
        self.assertEqual(
            health["health_status"],
            "healthy",
        )

    def test_archive_schema_is_initialized(self) -> None:
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        self.assertIn("workflow_job_archive", tables)
        self.assertIn("idx_workflow_job_archive_time", indexes)
        self.assertIn("idx_workflow_job_archive_user", indexes)


class WorkflowOperationsOpenApiTests(unittest.TestCase):

    def test_operations_routes_and_schemas(self) -> None:
        from app.main import app

        schema = app.openapi()
        paths = schema["paths"]

        for path in (
            "/api/v1/workflows/dead-letter/replay",
            "/api/v1/workflows/queue/archive",
            "/api/v1/workflows/workers/health",
        ):
            self.assertIn(path, paths)

        metrics = paths[
            "/api/v1/workflows/queue/metrics"
        ]["get"]
        parameter_names = {
            item["name"] for item in metrics["parameters"]
        }
        self.assertIn("window_seconds", parameter_names)

        components = schema["components"]["schemas"]
        for name in (
            "WorkflowDeadLetterReplayRequest",
            "WorkflowQueueArchiveRequest",
            "WorkflowArchivedJobListResponse",
            "WorkflowWorkerClusterHealthResponse",
        ):
            self.assertIn(name, components)

        retry = components["WorkflowQueueRetryRequest"]["properties"]
        self.assertIn("timeout_seconds", retry)


if __name__ == "__main__":
    unittest.main()
