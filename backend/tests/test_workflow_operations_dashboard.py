from __future__ import annotations

import sqlite3
import tempfile
import unittest

from pathlib import Path

from app.workflows.async_queue import WorkflowAsyncQueue
from app.workflows.schemas import ChapterWorkflowRequest


class WorkflowOperationsDashboardTests(
    unittest.TestCase
):

    def setUp(self) -> None:

        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

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
    ) -> ChapterWorkflowRequest:

        return ChapterWorkflowRequest(
            user_id=user_id,
            novel_id="novel001",
            instruction="Write.",
            max_revision_rounds=0,
        )

    def dead_letter(
        self,
        *,
        user_id: str = "user001",
    ) -> str:

        run_id, _ = self.queue.enqueue(
            self.request(
                user_id=user_id
            ),
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

        self.queue.handle_failure(
            run_id,
            worker_id=worker_id,
            error="forced failure",
        )

        return run_id

    def test_single_worker_control_is_audited(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-a",
            capacity=1,
        )

        self.queue.set_worker_control(
            "worker-a",
            control_mode="paused",
        )

        entries = (
            self.queue
            .list_operation_audit()
        )

        self.assertGreaterEqual(
            len(entries),
            1,
        )

        entry = entries[0]

        self.assertEqual(
            entry["operation_type"],
            "worker_control",
        )
        self.assertEqual(
            entry["target_id"],
            "worker-a",
        )
        self.assertEqual(
            entry["action"],
            "paused",
        )
        self.assertEqual(
            entry["status"],
            "success",
        )

    def test_d9_operations_are_audited(
        self,
    ) -> None:

        dead = self.dead_letter(
            user_id="user-dead"
        )

        replay = (
            self.queue
            .replay_dead_letters(
                [dead],
                max_queued_jobs=0,
                max_active_per_user=0,
            )
        )

        self.assertEqual(
            replay["replayed_count"],
            1,
        )

        cancelled, _ = (
            self.queue.enqueue(
                self.request(
                    user_id="user-cancel"
                ),
                max_queued_jobs=0,
                max_active_per_user=0,
            )
        )

        self.queue.request_cancel(
            cancelled
        )

        archived = (
            self.queue
            .archive_terminal_jobs(
                older_than_seconds=0.0,
                dry_run=False,
            )
        )

        self.assertIn(
            cancelled,
            archived["run_ids"],
        )

        types = {
            item["operation_type"]
            for item in (
                self.queue
                .list_operation_audit(
                    limit=20
                )
            )
        }

        self.assertIn(
            "dead_letter_replay",
            types,
        )
        self.assertIn(
            "queue_archive",
            types,
        )

    def test_bulk_worker_control(
        self,
    ) -> None:

        for worker_id in (
            "worker-a",
            "worker-b",
        ):
            self.queue.register_worker(
                worker_id,
                capacity=1,
            )

        result = (
            self.queue
            .bulk_set_worker_control(
                [
                    "worker-a",
                    "worker-b",
                ],
                action="pause",
            )
        )

        self.assertEqual(
            result["requested_count"],
            2,
        )
        self.assertEqual(
            result["succeeded_count"],
            2,
        )
        self.assertEqual(
            result["skipped_count"],
            0,
        )

        for worker_id in (
            "worker-a",
            "worker-b",
        ):
            control = (
                self.queue
                .get_worker_control(
                    worker_id
                )
            )

            self.assertEqual(
                control["control_mode"],
                "paused",
            )

    def test_bulk_worker_control_skips_missing(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-a",
            capacity=1,
        )

        result = (
            self.queue
            .bulk_set_worker_control(
                [
                    "worker-a",
                    "missing-worker",
                ],
                action="pause",
            )
        )

        self.assertEqual(
            result["succeeded_count"],
            1,
        )
        self.assertEqual(
            result["skipped_count"],
            1,
        )
        self.assertEqual(
            result["skipped"][0]["reason"],
            "not_found",
        )

    def test_worker_cleanup_dry_run_then_execute(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-old",
            capacity=1,
        )

        self.queue.mark_worker_stopped(
            "worker-old"
        )

        with sqlite3.connect(
            self.db_path
        ) as conn:

            conn.execute(
                """
                UPDATE workflow_workers
                SET heartbeat_at = ?,
                    stopped_at = ?
                WHERE worker_id = ?
                """,
                (
                    "2000-01-01T00:00:00+00:00",
                    "2000-01-01T00:00:00+00:00",
                    "worker-old",
                ),
            )

            conn.commit()

        preview = (
            self.queue
            .cleanup_worker_history(
                older_than_seconds=0.0,
                stale_after_seconds=10.0,
                dry_run=True,
            )
        )

        self.assertIn(
            "worker-old",
            preview["worker_ids"],
        )
        self.assertEqual(
            preview["deleted_count"],
            0,
        )

        executed = (
            self.queue
            .cleanup_worker_history(
                older_than_seconds=0.0,
                stale_after_seconds=10.0,
                dry_run=False,
            )
        )

        self.assertEqual(
            executed["deleted_count"],
            1,
        )

        worker_ids = {
            item["worker_id"]
            for item in (
                self.queue.list_workers()
            )
        }

        self.assertNotIn(
            "worker-old",
            worker_ids,
        )

    def test_worker_cleanup_removes_stale_not_live(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-stale",
            capacity=1,
        )

        self.queue.register_worker(
            "worker-live",
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

        result = (
            self.queue
            .cleanup_worker_history(
                older_than_seconds=0.0,
                stale_after_seconds=10.0,
                include_stale_running=True,
                dry_run=False,
            )
        )

        self.assertIn(
            "worker-stale",
            result["worker_ids"],
        )
        self.assertNotIn(
            "worker-live",
            result["worker_ids"],
        )

        remaining = {
            item["worker_id"]
            for item in (
                self.queue.list_workers()
            )
        }

        self.assertIn(
            "worker-live",
            remaining,
        )

    def test_alerts_report_worker_unavailable(
        self,
    ) -> None:

        result = (
            self.queue
            .evaluate_operational_alerts(
                ready_jobs_threshold=100,
                dead_letter_threshold=100,
            )
        )

        self.assertEqual(
            result["alert_status"],
            "critical",
        )

        codes = {
            item["code"]
            for item in result["alerts"]
        }

        self.assertIn(
            "worker_unavailable",
            codes,
        )

    def test_alerts_report_queue_backlog(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-a",
            capacity=2,
        )

        self.queue.enqueue(
            self.request(),
            max_queued_jobs=0,
            max_active_per_user=0,
        )

        result = (
            self.queue
            .evaluate_operational_alerts(
                ready_jobs_threshold=1,
                oldest_ready_seconds_threshold=9999.0,
                dead_letter_threshold=100,
                worker_utilization_threshold=1.0,
            )
        )

        codes = {
            item["code"]
            for item in result["alerts"]
        }

        self.assertIn(
            "queue_backlog",
            codes,
        )
        self.assertEqual(
            result["alert_status"],
            "warning",
        )

    def test_prometheus_metrics_exposition(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-a",
            capacity=1,
        )

        content = (
            self.queue
            .prometheus_metrics(
                window_seconds=60.0,
                stale_after_seconds=10.0,
            )
        )

        for marker in (
            "novelforge_workflow_queue_jobs",
            "novelforge_workflow_worker_running",
            "novelforge_workflow_worker_accepting",
            "novelforge_workflow_operations_audit_total",
            "novelforge_workflow_operational_alerts",
        ):
            self.assertIn(
                marker,
                content,
            )

        self.assertTrue(
            content.endswith("\n")
        )

    def test_dashboard_aggregates_operations(
        self,
    ) -> None:

        self.queue.register_worker(
            "worker-a",
            capacity=1,
        )

        self.queue.set_worker_control(
            "worker-a",
            control_mode="paused",
        )

        self.queue.set_worker_control(
            "worker-a",
            control_mode="running",
        )

        dashboard = (
            self.queue
            .operations_dashboard(
                window_seconds=60.0,
                stale_after_seconds=10.0,
                audit_limit=10,
            )
        )

        self.assertEqual(
            dashboard["workers"][
                "health_status"
            ],
            "healthy",
        )

        self.assertIn(
            "status_counts",
            dashboard["queue"],
        )

        self.assertGreaterEqual(
            len(
                dashboard[
                    "recent_audit"
                ]
            ),
            2,
        )

        self.assertIn(
            dashboard["alert_status"],
            {
                "ok",
                "warning",
                "critical",
            },
        )

    def test_audit_schema_is_initialized(
        self,
    ) -> None:

        with sqlite3.connect(
            self.db_path
        ) as conn:

            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }

            indexes = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                    """
                ).fetchall()
            }

        self.assertIn(
            "workflow_operations_audit",
            tables,
        )
        self.assertIn(
            "idx_workflow_operations_audit_time",
            indexes,
        )
        self.assertIn(
            "idx_workflow_operations_audit_type",
            indexes,
        )


class WorkflowOperationsDashboardOpenApiTests(
    unittest.TestCase
):

    def test_d10_routes_and_schemas(
        self,
    ) -> None:

        from app.main import app

        schema = app.openapi()
        paths = schema["paths"]

        for path in (
            "/api/v1/workflows/workers/control/batch",
            "/api/v1/workflows/workers/history/cleanup",
            "/api/v1/workflows/operations/audit",
            "/api/v1/workflows/operations/dashboard",
            "/api/v1/workflows/metrics/prometheus",
        ):
            self.assertIn(
                path,
                paths,
            )

        components = (
            schema["components"][
                "schemas"
            ]
        )

        for name in (
            "WorkflowWorkerBatchControlRequest",
            "WorkflowWorkerBatchControlResponse",
            "WorkflowWorkerHistoryCleanupRequest",
            "WorkflowWorkerHistoryCleanupResponse",
            "WorkflowOperationAuditListResponse",
            "WorkflowOperationsDashboardResponse",
        ):
            self.assertIn(
                name,
                components,
            )


if __name__ == "__main__":
    unittest.main()
