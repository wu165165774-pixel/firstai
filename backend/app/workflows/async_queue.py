from __future__ import annotations

import json
import os
import sqlite3
import uuid

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path
from typing import Any

from app.workflows.schemas import (
    ChapterWorkflowRequest,
)
from app.workflows.storage import (
    WorkflowRunStorage,
    _json_dumps,
    _utc_now,
)


class WorkflowAdmissionError(RuntimeError):

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retry_after_seconds: int = 1,
    ) -> None:

        super().__init__(message)
        self.code = code
        self.retry_after_seconds = max(
            int(retry_after_seconds),
            1,
        )


class WorkflowQueueFullError(
    WorkflowAdmissionError
):

    pass


class WorkflowUserQuotaError(
    WorkflowAdmissionError
):

    pass


class WorkflowAsyncQueue:
    """
    SQLite-backed queue for persisted
    chapter workflow runs.
    """

    def __init__(
        self,
        db_path: str | None = None,
    ) -> None:

        self.db_path = (
            db_path
            or os.getenv(
                "NOVELFORGE_WORKFLOW_DB_PATH",
                "/app/data/workflow_runs.db",
            )
        )

        Path(
            self.db_path
        ).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.run_storage = (
            WorkflowRunStorage(
                self.db_path
            )
        )

        self._init_db()

    def _connect(
        self,
    ) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.db_path,
            timeout=30.0,
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    def _init_db(
        self,
    ) -> None:

        with self._connect() as conn:

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS
                workflow_run_jobs (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT
                        UNIQUE,
                    queue_status TEXT
                        NOT NULL,
                    priority INTEGER
                        NOT NULL DEFAULT 0,
                    attempt_count INTEGER
                        NOT NULL DEFAULT 0,
                    max_attempts INTEGER
                        NOT NULL DEFAULT 3,
                    retry_base_seconds REAL
                        NOT NULL DEFAULT 2.0,
                    available_at TEXT
                        NOT NULL,
                    last_error TEXT,
                    dead_lettered_at TEXT,
                    cancel_requested INTEGER
                        NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    heartbeat_at TEXT,
                    queued_at TEXT
                        NOT NULL,
                    claimed_at TEXT,
                    updated_at TEXT
                        NOT NULL,
                    FOREIGN KEY(run_id)
                        REFERENCES workflow_runs(
                            run_id
                        )
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_jobs_status
                ON workflow_run_jobs(
                    queue_status,
                    queued_at
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_jobs_lease
                ON workflow_run_jobs(
                    queue_status,
                    lease_expires_at
                );

                CREATE TABLE IF NOT EXISTS
                workflow_workers (
                    worker_id TEXT PRIMARY KEY,
                    worker_status TEXT
                        NOT NULL,
                    capacity INTEGER
                        NOT NULL,
                    active_count INTEGER
                        NOT NULL DEFAULT 0,
                    started_at TEXT
                        NOT NULL,
                    heartbeat_at TEXT
                        NOT NULL,
                    stopped_at TEXT,
                    metadata_json TEXT
                        NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_workers_status
                ON workflow_workers(
                    worker_status,
                    heartbeat_at
                );
                """
            )

            columns = {
                row["name"]
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        workflow_run_jobs
                    )
                    """
                ).fetchall()
            }

            migrations = {
                "priority": (
                    "INTEGER NOT NULL "
                    "DEFAULT 0"
                ),
                "attempt_count": (
                    "INTEGER NOT NULL "
                    "DEFAULT 0"
                ),
                "max_attempts": (
                    "INTEGER NOT NULL "
                    "DEFAULT 3"
                ),
                "retry_base_seconds": (
                    "REAL NOT NULL "
                    "DEFAULT 2.0"
                ),
                "available_at": (
                    "TEXT NOT NULL "
                    "DEFAULT ''"
                ),
                "last_error": "TEXT",
                "dead_lettered_at": "TEXT",
            }

            for column_name, definition in (
                migrations.items()
            ):

                if column_name in columns:

                    continue

                conn.execute(
                    "ALTER TABLE "
                    "workflow_run_jobs "
                    f"ADD COLUMN {column_name} "
                    f"{definition}"
                )

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET available_at = queued_at
                WHERE available_at IS NULL
                OR available_at = ''
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_workflow_jobs_schedule
                ON workflow_run_jobs(
                    queue_status,
                    available_at,
                    priority DESC,
                    queued_at
                )
                """
            )

            conn.commit()

    @staticmethod
    def _normalize_key(
        value: str | None,
    ) -> str | None:

        if value is None:

            return None

        normalized = value.strip()

        if not normalized:

            return None

        if len(normalized) > 128:

            raise ValueError(
                "Idempotency key must not "
                "exceed 128 characters."
            )

        return normalized

    @staticmethod
    def _next_sequence(
        conn: sqlite3.Connection,
        run_id: str,
    ) -> int:

        row = conn.execute(
            """
            SELECT COALESCE(
                MAX(sequence_no),
                -1
            ) AS max_sequence
            FROM workflow_run_events
            WHERE run_id = ?
            """,
            (
                run_id,
            ),
        ).fetchone()

        return (
            int(
                row["max_sequence"]
            )
            + 1
        )

    @staticmethod
    def _lease_expiry(
        lease_seconds: float,
    ) -> str:

        return (
            datetime.now(
                timezone.utc
            )
            + timedelta(
                seconds=max(
                    float(
                        lease_seconds
                    ),
                    0.05,
                )
            )
        ).isoformat()

    @staticmethod
    def _normalize_priority(
        priority: int,
    ) -> int:

        normalized = int(
            priority
        )

        if not -100 <= normalized <= 100:

            raise ValueError(
                "Workflow priority must be "
                "between -100 and 100."
            )

        return normalized

    @staticmethod
    def _normalize_max_attempts(
        max_attempts: int,
    ) -> int:

        normalized = int(
            max_attempts
        )

        if not 1 <= normalized <= 10:

            raise ValueError(
                "Workflow max attempts must "
                "be between 1 and 10."
            )

        return normalized

    @staticmethod
    def _normalize_retry_base(
        retry_base_seconds: float,
    ) -> float:

        normalized = float(
            retry_base_seconds
        )

        if not 0.01 <= normalized <= 3600.0:

            raise ValueError(
                "Workflow retry base seconds "
                "must be between 0.01 and 3600."
            )

        return normalized

    @staticmethod
    def _available_time(
        delay_seconds: float,
    ) -> str:

        return (
            datetime.now(
                timezone.utc
            )
            + timedelta(
                seconds=max(
                    float(
                        delay_seconds
                    ),
                    0.0,
                )
            )
        ).isoformat()

    def enqueue(
        self,
        request: ChapterWorkflowRequest,
        *,
        idempotency_key: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        retry_base_seconds: float = 2.0,
        timeout_seconds: float = 900.0,
        max_queued_jobs: int = 1000,
        max_active_per_user: int = 8,
    ) -> tuple[
        str,
        bool,
    ]:

        normalized_key = (
            self._normalize_key(
                idempotency_key
            )
        )

        normalized_priority = (
            self._normalize_priority(
                priority
            )
        )

        normalized_max_attempts = (
            self._normalize_max_attempts(
                max_attempts
            )
        )

        normalized_retry_base = (
            self._normalize_retry_base(
                retry_base_seconds
            )
        )

        normalized_timeout = (
            self._normalize_timeout(
                timeout_seconds
            )
        )

        normalized_queue_limit = max(
            int(max_queued_jobs),
            0,
        )

        normalized_user_limit = max(
            int(max_active_per_user),
            0,
        )

        run_id = str(
            uuid.uuid4()
        )

        now = _utc_now()

        request_payload = (
            request.model_dump(
                mode="json"
            )
        )

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            if normalized_key is not None:

                existing = conn.execute(
                    """
                    SELECT run_id
                    FROM workflow_run_jobs
                    WHERE idempotency_key = ?
                    """,
                    (
                        normalized_key,
                    ),
                ).fetchone()

                if existing is not None:

                    conn.commit()

                    return (
                        existing["run_id"],
                        True,
                    )

            if normalized_queue_limit > 0:

                queued_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM workflow_run_jobs
                        WHERE queue_status IN (
                            'queued',
                            'retry_wait'
                        )
                        """
                    ).fetchone()["count"]
                )

                if queued_count >= normalized_queue_limit:

                    self._increment_counter(
                        conn,
                        "queue_full_rejections",
                    )
                    conn.commit()
                    raise WorkflowQueueFullError(
                        "Workflow queue is full.",
                        code="queue_full",
                    )

            if normalized_user_limit > 0:

                active_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM workflow_run_jobs AS jobs
                        JOIN workflow_runs AS runs
                            ON runs.run_id = jobs.run_id
                        WHERE runs.user_id = ?
                        AND jobs.queue_status IN (
                            'queued',
                            'retry_wait',
                            'running',
                            'cancelling'
                        )
                        """,
                        (request.user_id,),
                    ).fetchone()["count"]
                )

                if active_count >= normalized_user_limit:

                    self._increment_counter(
                        conn,
                        "user_quota_rejections",
                    )
                    conn.commit()
                    raise WorkflowUserQuotaError(
                        "Workflow active-job quota "
                        "was reached for this user.",
                        code="user_quota_exceeded",
                    )

            conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id,
                    root_run_id,
                    parent_run_id,
                    user_id,
                    novel_id,
                    workflow_type,
                    execution_status,
                    workflow_status,
                    quality_gate_passed,
                    resumable,
                    revision_rounds,
                    request_json,
                    result_json,
                    latest_content,
                    error,
                    created_at,
                    updated_at,
                    completed_at
                )
                VALUES (
                    ?,
                    ?,
                    NULL,
                    ?,
                    ?,
                    'chapter_production',
                    'queued',
                    NULL,
                    0,
                    0,
                    0,
                    ?,
                    NULL,
                    '',
                    NULL,
                    ?,
                    ?,
                    NULL
                )
                """,
                (
                    run_id,
                    run_id,
                    request.user_id,
                    request.novel_id,
                    _json_dumps(
                        request_payload
                    ),
                    now,
                    now,
                ),
            )

            conn.execute(
                """
                INSERT INTO workflow_run_jobs (
                    run_id,
                    idempotency_key,
                    queue_status,
                    priority,
                    attempt_count,
                    max_attempts,
                    retry_base_seconds,
                    timeout_seconds,
                    timed_out_count,
                    available_at,
                    last_error,
                    dead_lettered_at,
                    cancel_requested,
                    lease_owner,
                    lease_expires_at,
                    heartbeat_at,
                    queued_at,
                    claimed_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    'queued',
                    ?,
                    0,
                    ?,
                    ?,
                    ?,
                    0,
                    ?,
                    NULL,
                    NULL,
                    0,
                    NULL,
                    NULL,
                    NULL,
                    ?,
                    NULL,
                    ?
                )
                """,
                (
                    run_id,
                    normalized_key,
                    normalized_priority,
                    normalized_max_attempts,
                    normalized_retry_base,
                    normalized_timeout,
                    now,
                    now,
                    now,
                ),
            )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=0,
                event_type="run_queued",
                payload={
                    "idempotency_key": (
                        normalized_key
                    ),
                    "priority": (
                        normalized_priority
                    ),
                    "max_attempts": (
                        normalized_max_attempts
                    ),
                    "retry_base_seconds": (
                        normalized_retry_base
                    ),
                    "timeout_seconds": (
                        normalized_timeout
                    ),
                    "max_queued_jobs": (
                        normalized_queue_limit
                    ),
                    "max_active_per_user": (
                        normalized_user_limit
                    ),
                },
            )

            conn.commit()

        return (
            run_id,
            False,
        )

    def get_control(
        self,
        run_id: str,
    ) -> dict[str, Any]:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

        if row is None:

            raise KeyError(
                f"Workflow job not found: "
                f"{run_id}"
            )

        return {
            "run_id": row["run_id"],
            "queue_status": (
                row["queue_status"]
            ),
            "idempotency_key": (
                row["idempotency_key"]
            ),
            "priority": int(
                row["priority"]
            ),
            "attempt_count": int(
                row["attempt_count"]
            ),
            "max_attempts": int(
                row["max_attempts"]
            ),
            "retry_base_seconds": float(
                row["retry_base_seconds"]
            ),
            "timeout_seconds": float(
                row["timeout_seconds"]
            ),
            "timed_out_count": int(
                row["timed_out_count"]
            ),
            "available_at": (
                row["available_at"]
            ),
            "last_error": (
                row["last_error"]
            ),
            "dead_lettered_at": (
                row["dead_lettered_at"]
            ),
            "cancel_requested": bool(
                row["cancel_requested"]
            ),
            "lease_owner": (
                row["lease_owner"]
            ),
            "lease_expires_at": (
                row["lease_expires_at"]
            ),
            "heartbeat_at": (
                row["heartbeat_at"]
            ),
            "queued_at": (
                row["queued_at"]
            ),
            "claimed_at": (
                row["claimed_at"]
            ),
            "updated_at": (
                row["updated_at"]
            ),
        }

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> tuple[
        str,
        ChapterWorkflowRequest,
    ] | None:

        now = _utc_now()

        lease_expires_at = (
            self._lease_expiry(
                lease_seconds
            )
        )

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = conn.execute(
                """
                SELECT
                    jobs.run_id,
                    jobs.queue_status,
                    jobs.priority,
                    jobs.attempt_count,
                    jobs.max_attempts,
                    runs.request_json
                FROM workflow_run_jobs
                    AS jobs
                JOIN workflow_runs
                    AS runs
                    ON runs.run_id =
                        jobs.run_id
                WHERE jobs.queue_status
                    IN (
                        'queued',
                        'retry_wait'
                    )
                AND jobs.available_at <= ?
                ORDER BY
                    jobs.priority DESC,
                    jobs.available_at ASC,
                    jobs.queued_at ASC
                LIMIT 1
                """,
                (
                    now,
                ),
            ).fetchone()

            if row is None:

                conn.commit()

                return None

            run_id = row["run_id"]

            attempt_count = (
                int(
                    row["attempt_count"]
                )
                + 1
            )

            previous_queue_status = (
                row["queue_status"]
            )

            updated = conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status =
                        'running',
                    attempt_count = ?,
                    lease_owner = ?,
                    lease_expires_at = ?,
                    heartbeat_at = ?,
                    claimed_at =
                        COALESCE(
                            claimed_at,
                            ?
                        ),
                    updated_at = ?
                WHERE run_id = ?
                AND queue_status IN (
                    'queued',
                    'retry_wait'
                )
                AND available_at <= ?
                """,
                (
                    attempt_count,
                    worker_id,
                    lease_expires_at,
                    now,
                    now,
                    now,
                    run_id,
                    now,
                ),
            ).rowcount

            if updated != 1:

                conn.rollback()

                return None

            conn.execute(
                """
                UPDATE workflow_runs
                SET
                    execution_status =
                        'running',
                    updated_at = ?,
                    completed_at = NULL
                WHERE run_id = ?
                """,
                (
                    now,
                    run_id,
                ),
            )

            sequence_no = (
                self._next_sequence(
                    conn,
                    run_id,
                )
            )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=(
                    sequence_no
                ),
                event_type="run_claimed",
                payload={
                    "worker_id": worker_id,
                    "lease_expires_at": (
                        lease_expires_at
                    ),
                    "priority": int(
                        row["priority"]
                    ),
                    "attempt_count": (
                        attempt_count
                    ),
                    "max_attempts": int(
                        row["max_attempts"]
                    ),
                    "previous_queue_status": (
                        previous_queue_status
                    ),
                },
            )

            conn.commit()

        request_payload = json.loads(
            row["request_json"]
        )

        return (
            run_id,
            ChapterWorkflowRequest
            .model_validate(
                request_payload
            ),
        )

    def heartbeat(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> bool:

        now = _utc_now()

        lease_expires_at = (
            self._lease_expiry(
                lease_seconds
            )
        )

        with self._connect() as conn:

            updated = conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    heartbeat_at = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE run_id = ?
                AND lease_owner = ?
                AND queue_status IN (
                    'running',
                    'cancelling'
                )
                """,
                (
                    now,
                    lease_expires_at,
                    now,
                    run_id,
                    worker_id,
                ),
            ).rowcount

            conn.commit()

        return updated == 1

    def is_cancel_requested(
        self,
        run_id: str,
    ) -> bool:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT cancel_requested
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

        if row is None:

            raise KeyError(
                f"Workflow job not found: "
                f"{run_id}"
            )

        return bool(
            row["cancel_requested"]
        )

    def request_cancel(
        self,
        run_id: str,
    ) -> dict[str, Any]:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = conn.execute(
                """
                SELECT queue_status
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if row is None:

                conn.rollback()

                raise KeyError(
                    f"Workflow job not "
                    f"found: {run_id}"
                )

            queue_status = (
                row["queue_status"]
            )

            if queue_status in {
                "cancelled",
                "completed",
                "failed",
                "dead_letter",
            }:

                conn.commit()

                return self.get_control(
                    run_id
                )

            sequence_no = (
                self._next_sequence(
                    conn,
                    run_id,
                )
            )

            if queue_status in {
                "queued",
                "retry_wait",
            }:

                conn.execute(
                    """
                    UPDATE workflow_run_jobs
                    SET
                        queue_status =
                            'cancelled',
                        cancel_requested = 1,
                        lease_owner = NULL,
                        lease_expires_at =
                            NULL,
                        heartbeat_at = NULL,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        now,
                        run_id,
                    ),
                )

                conn.execute(
                    """
                    UPDATE workflow_runs
                    SET
                        execution_status =
                            'cancelled',
                        resumable = 0,
                        updated_at = ?,
                        completed_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        now,
                        now,
                        run_id,
                    ),
                )

                event_type = (
                    "run_cancelled"
                )

            else:

                conn.execute(
                    """
                    UPDATE workflow_run_jobs
                    SET
                        queue_status =
                            'cancelling',
                        cancel_requested = 1,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        now,
                        run_id,
                    ),
                )

                conn.execute(
                    """
                    UPDATE workflow_runs
                    SET
                        execution_status =
                            'cancelling',
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        now,
                        run_id,
                    ),
                )

                event_type = (
                    "cancel_requested"
                )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=(
                    sequence_no
                ),
                event_type=event_type,
                payload={
                    "previous_queue_status": (
                        queue_status
                    ),
                },
            )

            conn.commit()

        return self.get_control(
            run_id
        )

    def mark_cancelled(
        self,
        run_id: str,
        *,
        reason: str,
    ) -> None:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = conn.execute(
                """
                SELECT queue_status
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if row is None:

                conn.rollback()

                raise KeyError(
                    f"Workflow job not "
                    f"found: {run_id}"
                )

            if (
                row["queue_status"]
                == "cancelled"
            ):

                conn.commit()

                return

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status =
                        'cancelled',
                    cancel_requested = 1,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    run_id,
                ),
            )

            conn.execute(
                """
                UPDATE workflow_runs
                SET
                    execution_status =
                        'cancelled',
                    resumable = 0,
                    error = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE run_id = ?
                """,
                (
                    reason,
                    now,
                    now,
                    run_id,
                ),
            )

            sequence_no = (
                self._next_sequence(
                    conn,
                    run_id,
                )
            )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=(
                    sequence_no
                ),
                event_type="run_cancelled",
                payload={
                    "reason": reason
                },
            )

            conn.commit()

    def mark_terminal(
        self,
        run_id: str,
    ) -> None:

        now = _utc_now()

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT execution_status
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if row is None:

                raise KeyError(
                    f"Workflow run not found: "
                    f"{run_id}"
                )

            queue_status = (
                "failed"
                if row[
                    "execution_status"
                ]
                == "failed"
                else "completed"
            )

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    queue_status,
                    now,
                    run_id,
                ),
            )

            conn.commit()

    def mark_failed(
        self,
        run_id: str,
    ) -> None:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status = 'failed',
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    run_id,
                ),
            )

            conn.commit()

    def handle_failure(
        self,
        run_id: str,
        *,
        worker_id: str,
        error: str,
        max_retry_delay_seconds: float = 300.0,
    ) -> dict[str, Any]:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = conn.execute(
                """
                SELECT
                    queue_status,
                    lease_owner,
                    cancel_requested,
                    attempt_count,
                    max_attempts,
                    retry_base_seconds
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if row is None:

                conn.rollback()

                raise KeyError(
                    f"Workflow job not found: "
                    f"{run_id}"
                )

            if (
                row["lease_owner"]
                != worker_id
                or row["queue_status"]
                not in {
                    "running",
                    "cancelling",
                }
            ):

                conn.rollback()

                return self.get_control(
                    run_id
                )

            if bool(
                row["cancel_requested"]
            ):

                conn.rollback()

                self.mark_cancelled(
                    run_id,
                    reason=(
                        "Cancellation requested "
                        "while handling failure."
                    ),
                )

                return self.get_control(
                    run_id
                )

            attempt_count = int(
                row["attempt_count"]
            )

            max_attempts = int(
                row["max_attempts"]
            )

            sequence_no = (
                self._next_sequence(
                    conn,
                    run_id,
                )
            )

            if attempt_count < max_attempts:

                retry_base = float(
                    row[
                        "retry_base_seconds"
                    ]
                )

                delay_seconds = min(
                    retry_base
                    * (
                        2
                        ** max(
                            attempt_count - 1,
                            0,
                        )
                    ),
                    max(
                        float(
                            max_retry_delay_seconds
                        ),
                        0.01,
                    ),
                )

                available_at = (
                    self._available_time(
                        delay_seconds
                    )
                )

                conn.execute(
                    """
                    UPDATE workflow_run_jobs
                    SET
                        queue_status =
                            'retry_wait',
                        available_at = ?,
                        last_error = ?,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        available_at,
                        error,
                        now,
                        run_id,
                    ),
                )

                conn.execute(
                    """
                    UPDATE workflow_runs
                    SET
                        execution_status =
                            'retrying',
                        error = ?,
                        resumable = 0,
                        updated_at = ?,
                        completed_at = NULL
                    WHERE run_id = ?
                    """,
                    (
                        error,
                        now,
                        run_id,
                    ),
                )

                WorkflowRunStorage._insert_event(
                    conn,
                    run_id=run_id,
                    sequence_no=(
                        sequence_no
                    ),
                    event_type=(
                        "retry_scheduled"
                    ),
                    payload={
                        "worker_id": worker_id,
                        "attempt_count": (
                            attempt_count
                        ),
                        "max_attempts": (
                            max_attempts
                        ),
                        "delay_seconds": (
                            delay_seconds
                        ),
                        "available_at": (
                            available_at
                        ),
                        "error": error,
                    },
                )

            else:

                conn.execute(
                    """
                    UPDATE workflow_run_jobs
                    SET
                        queue_status =
                            'dead_letter',
                        available_at = ?,
                        last_error = ?,
                        dead_lettered_at = ?,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        now,
                        error,
                        now,
                        now,
                        run_id,
                    ),
                )

                conn.execute(
                    """
                    UPDATE workflow_runs
                    SET
                        execution_status =
                            'dead_letter',
                        error = ?,
                        resumable = 0,
                        updated_at = ?,
                        completed_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        error,
                        now,
                        now,
                        run_id,
                    ),
                )

                WorkflowRunStorage._insert_event(
                    conn,
                    run_id=run_id,
                    sequence_no=(
                        sequence_no
                    ),
                    event_type=(
                        "run_dead_lettered"
                    ),
                    payload={
                        "worker_id": worker_id,
                        "attempt_count": (
                            attempt_count
                        ),
                        "max_attempts": (
                            max_attempts
                        ),
                        "error": error,
                    },
                )

            conn.commit()

        return self.get_control(
            run_id
        )

    def retry_run(
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
    ) -> dict[str, Any]:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = conn.execute(
                """
                SELECT *
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if row is None:

                conn.rollback()

                raise KeyError(
                    f"Workflow job not found: "
                    f"{run_id}"
                )

            if row["queue_status"] not in {
                "dead_letter",
                "failed",
            }:

                conn.rollback()

                raise ValueError(
                    "Only failed or dead-letter "
                    "workflow runs can be retried."
                )

            normalized_priority = (
                int(
                    row["priority"]
                )
                if priority is None
                else self._normalize_priority(
                    priority
                )
            )

            normalized_max_attempts = (
                int(
                    row["max_attempts"]
                )
                if max_attempts is None
                else (
                    self
                    ._normalize_max_attempts(
                        max_attempts
                    )
                )
            )

            normalized_retry_base = (
                float(
                    row[
                        "retry_base_seconds"
                    ]
                )
                if retry_base_seconds is None
                else (
                    self
                    ._normalize_retry_base(
                        retry_base_seconds
                    )
                )
            )

            normalized_timeout = (
                float(
                    row[
                        "timeout_seconds"
                    ]
                )
                if timeout_seconds is None
                else self._normalize_timeout(
                    timeout_seconds
                )
            )

            attempt_count = (
                0
                if reset_attempts
                else int(
                    row["attempt_count"]
                )
            )

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status = 'queued',
                    priority = ?,
                    attempt_count = ?,
                    max_attempts = ?,
                    retry_base_seconds = ?,
                    timeout_seconds = ?,
                    available_at = ?,
                    last_error = NULL,
                    dead_lettered_at = NULL,
                    cancel_requested = 0,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    claimed_at = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    normalized_priority,
                    attempt_count,
                    normalized_max_attempts,
                    normalized_retry_base,
                    normalized_timeout,
                    now,
                    now,
                    run_id,
                ),
            )

            conn.execute(
                """
                UPDATE workflow_runs
                SET
                    execution_status =
                        'queued',
                    error = NULL,
                    resumable = 0,
                    result_json = NULL,
                    latest_content = '',
                    workflow_status = NULL,
                    quality_gate_passed = 0,
                    revision_rounds = 0,
                    updated_at = ?,
                    completed_at = NULL
                WHERE run_id = ?
                """,
                (
                    now,
                    run_id,
                ),
            )

            conn.execute(
                """
                DELETE FROM
                    workflow_chapter_versions
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            )

            sequence_no = (
                self._next_sequence(
                    conn,
                    run_id,
                )
            )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=(
                    sequence_no
                ),
                event_type="run_requeued",
                payload={
                    "reset_attempts": (
                        reset_attempts
                    ),
                    "priority": (
                        normalized_priority
                    ),
                    "max_attempts": (
                        normalized_max_attempts
                    ),
                    "retry_base_seconds": (
                        normalized_retry_base
                    ),
                    "timeout_seconds": (
                        normalized_timeout
                    ),
                },
            )

            conn.commit()

        return self.get_control(
            run_id
        )

    def queue_metrics(
        self,
        *,
        worker_stale_after_seconds: float = 90.0,
    ) -> dict[str, Any]:

        now = _utc_now()

        with self._connect() as conn:

            status_rows = conn.execute(
                """
                SELECT
                    queue_status,
                    COUNT(*) AS count
                FROM workflow_run_jobs
                GROUP BY queue_status
                """
            ).fetchall()

            ready_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM workflow_run_jobs
                WHERE queue_status IN (
                    'queued',
                    'retry_wait'
                )
                AND available_at <= ?
                """,
                (
                    now,
                ),
            ).fetchone()

            delayed_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM workflow_run_jobs
                WHERE queue_status =
                    'retry_wait'
                AND available_at > ?
                """,
                (
                    now,
                ),
            ).fetchone()

            priority_row = conn.execute(
                """
                SELECT
                    MIN(priority) AS minimum,
                    MAX(priority) AS maximum,
                    AVG(priority) AS average
                FROM workflow_run_jobs
                """
            ).fetchone()

        status_counts = {
            row["queue_status"]: int(
                row["count"]
            )
            for row in status_rows
        }

        workers = self.list_workers(
            stale_after_seconds=(
                worker_stale_after_seconds
            )
        )

        worker_status_counts: dict[
            str,
            int,
        ] = {}

        for worker in workers:

            worker_status = worker[
                "worker_status"
            ]

            worker_status_counts[
                worker_status
            ] = (
                worker_status_counts.get(
                    worker_status,
                    0,
                )
                + 1
            )

        total_jobs = sum(
            status_counts.values()
        )

        average = priority_row[
            "average"
        ]

        return {
            "total_jobs": total_jobs,
            "status_counts": (
                status_counts
            ),
            "ready_count": int(
                ready_row["count"]
            ),
            "delayed_retry_count": int(
                delayed_row["count"]
            ),
            "dead_letter_count": int(
                status_counts.get(
                    "dead_letter",
                    0,
                )
            ),
            "priority_min": (
                int(
                    priority_row[
                        "minimum"
                    ]
                )
                if priority_row[
                    "minimum"
                ]
                is not None
                else None
            ),
            "priority_max": (
                int(
                    priority_row[
                        "maximum"
                    ]
                )
                if priority_row[
                    "maximum"
                ]
                is not None
                else None
            ),
            "priority_average": (
                float(
                    average
                )
                if average is not None
                else None
            ),
            "worker_status_counts": (
                worker_status_counts
            ),
        }

    def list_dead_letters(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        normalized_limit = min(
            max(
                int(limit),
                1,
            ),
            500,
        )

        with self._connect() as conn:

            rows = conn.execute(
                """
                SELECT
                    jobs.run_id,
                    runs.user_id,
                    runs.novel_id,
                    jobs.priority,
                    jobs.attempt_count,
                    jobs.max_attempts,
                    jobs.retry_base_seconds,
                    jobs.last_error,
                    jobs.dead_lettered_at,
                    jobs.updated_at
                FROM workflow_run_jobs
                    AS jobs
                JOIN workflow_runs
                    AS runs
                    ON runs.run_id =
                        jobs.run_id
                WHERE jobs.queue_status =
                    'dead_letter'
                ORDER BY
                    jobs.dead_lettered_at DESC,
                    jobs.updated_at DESC
                LIMIT ?
                """,
                (
                    normalized_limit,
                ),
            ).fetchall()

        return [
            {
                "run_id": row["run_id"],
                "user_id": row["user_id"],
                "novel_id": row["novel_id"],
                "priority": int(
                    row["priority"]
                ),
                "attempt_count": int(
                    row["attempt_count"]
                ),
                "max_attempts": int(
                    row["max_attempts"]
                ),
                "retry_base_seconds": float(
                    row[
                        "retry_base_seconds"
                    ]
                ),
                "last_error": (
                    row["last_error"]
                ),
                "dead_lettered_at": (
                    row[
                        "dead_lettered_at"
                    ]
                ),
                "updated_at": (
                    row["updated_at"]
                ),
            }
            for row in rows
        ]

    def register_worker(
        self,
        worker_id: str,
        *,
        capacity: int,
        metadata: dict[str, Any]
        | None = None,
    ) -> None:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                """
                INSERT INTO workflow_workers (
                    worker_id,
                    worker_status,
                    capacity,
                    active_count,
                    started_at,
                    heartbeat_at,
                    stopped_at,
                    metadata_json
                )
                VALUES (
                    ?,
                    'running',
                    ?,
                    0,
                    ?,
                    ?,
                    NULL,
                    ?
                )
                ON CONFLICT(worker_id)
                DO UPDATE SET
                    worker_status =
                        'running',
                    capacity =
                        excluded.capacity,
                    active_count = 0,
                    started_at =
                        excluded.started_at,
                    heartbeat_at =
                        excluded.heartbeat_at,
                    stopped_at = NULL,
                    metadata_json =
                        excluded.metadata_json
                """,
                (
                    worker_id,
                    max(
                        int(capacity),
                        1,
                    ),
                    now,
                    now,
                    _json_dumps(
                        metadata or {}
                    ),
                ),
            )

            conn.commit()

    def heartbeat_worker(
        self,
        worker_id: str,
        *,
        active_count: int,
    ) -> bool:

        now = _utc_now()

        with self._connect() as conn:

            updated = conn.execute(
                """
                UPDATE workflow_workers
                SET
                    worker_status =
                        'running',
                    active_count = ?,
                    heartbeat_at = ?,
                    stopped_at = NULL
                WHERE worker_id = ?
                """,
                (
                    max(
                        int(active_count),
                        0,
                    ),
                    now,
                    worker_id,
                ),
            ).rowcount

            conn.commit()

        return updated == 1

    def mark_worker_stopping(
        self,
        worker_id: str,
    ) -> None:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                """
                UPDATE workflow_workers
                SET
                    worker_status =
                        'stopping',
                    heartbeat_at = ?
                WHERE worker_id = ?
                """,
                (
                    now,
                    worker_id,
                ),
            )

            conn.commit()

    def mark_worker_stopped(
        self,
        worker_id: str,
    ) -> None:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                """
                UPDATE workflow_workers
                SET
                    worker_status =
                        'stopped',
                    active_count = 0,
                    heartbeat_at = ?,
                    stopped_at = ?
                WHERE worker_id = ?
                """,
                (
                    now,
                    now,
                    worker_id,
                ),
            )

            conn.commit()

    def list_workers(
        self,
        *,
        stale_after_seconds: float = 90.0,
    ) -> list[dict[str, Any]]:

        with self._connect() as conn:

            rows = conn.execute(
                """
                SELECT *
                FROM workflow_workers
                ORDER BY started_at ASC
                """
            ).fetchall()

        now = datetime.now(
            timezone.utc
        )

        stale_after = max(
            float(
                stale_after_seconds
            ),
            0.0,
        )

        workers: list[
            dict[str, Any]
        ] = []

        for row in rows:

            heartbeat_at = (
                datetime.fromisoformat(
                    row["heartbeat_at"]
                )
            )

            worker_status = (
                row["worker_status"]
            )

            is_stale = (
                worker_status
                in {
                    "running",
                    "stopping",
                }
                and (
                    now - heartbeat_at
                ).total_seconds()
                > stale_after
            )

            effective_status = (
                "stale"
                if is_stale
                else worker_status
            )

            workers.append(
                {
                    "worker_id": (
                        row["worker_id"]
                    ),
                    "worker_status": (
                        effective_status
                    ),
                    "capacity": int(
                        row["capacity"]
                    ),
                    "active_count": int(
                        row[
                            "active_count"
                        ]
                    ),
                    "started_at": (
                        row["started_at"]
                    ),
                    "heartbeat_at": (
                        row["heartbeat_at"]
                    ),
                    "stopped_at": (
                        row["stopped_at"]
                    ),
                    "metadata": json.loads(
                        row[
                            "metadata_json"
                        ]
                        or "{}"
                    ),
                }
            )

        return workers

    def release_claim(
        self,
        run_id: str,
        *,
        worker_id: str,
        reason: str,
    ) -> bool:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = conn.execute(
                """
                SELECT
                    queue_status,
                    cancel_requested,
                    lease_owner
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if row is None:

                conn.rollback()

                raise KeyError(
                    f"Workflow job not "
                    f"found: {run_id}"
                )

            if (
                row["lease_owner"]
                != worker_id
                or row["queue_status"]
                not in {
                    "running",
                    "cancelling",
                }
            ):

                conn.rollback()

                return False

            if bool(
                row["cancel_requested"]
            ):

                conn.rollback()

                self.mark_cancelled(
                    run_id,
                    reason=reason,
                )

                return True

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status = 'queued',
                    available_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    now,
                    run_id,
                ),
            )

            conn.execute(
                """
                UPDATE workflow_runs
                SET
                    execution_status =
                        'queued',
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    run_id,
                ),
            )

            sequence_no = (
                self._next_sequence(
                    conn,
                    run_id,
                )
            )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=(
                    sequence_no
                ),
                event_type="worker_released",
                payload={
                    "worker_id": worker_id,
                    "reason": reason,
                },
            )

            conn.commit()

        return True

    def recover_stale(
        self,
    ) -> list[str]:

        now = _utc_now()

        recovered: list[str] = []

        with self._connect() as conn:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            rows = conn.execute(
                """
                SELECT
                    run_id,
                    queue_status,
                    cancel_requested
                FROM workflow_run_jobs
                WHERE queue_status IN (
                    'running',
                    'cancelling'
                )
                AND lease_expires_at
                    IS NOT NULL
                AND lease_expires_at < ?
                """,
                (
                    now,
                ),
            ).fetchall()

            for row in rows:

                run_id = row["run_id"]

                should_cancel = (
                    bool(
                        row[
                            "cancel_requested"
                        ]
                    )
                    or row["queue_status"]
                    == "cancelling"
                )

                sequence_no = (
                    self._next_sequence(
                        conn,
                        run_id,
                    )
                )

                if should_cancel:

                    conn.execute(
                        """
                        UPDATE
                            workflow_run_jobs
                        SET
                            queue_status =
                                'cancelled',
                            lease_owner = NULL,
                            lease_expires_at =
                                NULL,
                            heartbeat_at = NULL,
                            updated_at = ?
                        WHERE run_id = ?
                        """,
                        (
                            now,
                            run_id,
                        ),
                    )

                    conn.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            execution_status =
                                'cancelled',
                            resumable = 0,
                            error = (
                                'Cancelled after '
                                'worker lease expired.'
                            ),
                            updated_at = ?,
                            completed_at = ?
                        WHERE run_id = ?
                        """,
                        (
                            now,
                            now,
                            run_id,
                        ),
                    )

                    event_type = (
                        "run_cancelled"
                    )

                else:

                    conn.execute(
                        """
                        UPDATE
                            workflow_run_jobs
                        SET
                            queue_status =
                                'queued',
                            available_at = ?,
                            lease_owner = NULL,
                            lease_expires_at =
                                NULL,
                            heartbeat_at = NULL,
                            updated_at = ?
                        WHERE run_id = ?
                        """,
                        (
                            now,
                            now,
                            run_id,
                        ),
                    )

                    conn.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            execution_status =
                                'queued',
                            updated_at = ?
                        WHERE run_id = ?
                        """,
                        (
                            now,
                            run_id,
                        ),
                    )

                    event_type = (
                        "lease_recovered"
                    )

                WorkflowRunStorage._insert_event(
                    conn,
                    run_id=run_id,
                    sequence_no=(
                        sequence_no
                    ),
                    event_type=event_type,
                    payload={
                        "previous_queue_status": (
                            row[
                                "queue_status"
                            ]
                        ),
                    },
                )

                recovered.append(
                    run_id
                )

            conn.commit()

        return recovered

    _init_db_d7 = _init_db
    _register_worker_d7 = register_worker
    _heartbeat_worker_d7 = heartbeat_worker
    _list_workers_d7 = list_workers
    _queue_metrics_d7 = queue_metrics

    def _init_db(
        self,
    ) -> None:

        self._init_db_d7()

        with self._connect() as conn:

            job_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(workflow_run_jobs)"
                ).fetchall()
            }

            for name, definition in {
                "timeout_seconds": (
                    "REAL NOT NULL DEFAULT 900.0"
                ),
                "timed_out_count": (
                    "INTEGER NOT NULL DEFAULT 0"
                ),
            }.items():

                if name not in job_columns:
                    conn.execute(
                        "ALTER TABLE workflow_run_jobs "
                        f"ADD COLUMN {name} {definition}"
                    )

            worker_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(workflow_workers)"
                ).fetchall()
            }

            for name, definition in {
                "control_mode": (
                    "TEXT NOT NULL DEFAULT 'running'"
                ),
                "control_updated_at": "TEXT",
            }.items():

                if name not in worker_columns:
                    conn.execute(
                        "ALTER TABLE workflow_workers "
                        f"ADD COLUMN {name} {definition}"
                    )

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS
                workflow_queue_counters (
                    counter_name TEXT PRIMARY KEY,
                    counter_value INTEGER
                        NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_workers_control
                ON workflow_workers(
                    control_mode,
                    heartbeat_at
                );
                """
            )

            conn.commit()

    @staticmethod
    def _normalize_timeout(
        timeout_seconds: float,
    ) -> float:

        normalized = float(timeout_seconds)

        if not 0.1 <= normalized <= 86400.0:
            raise ValueError(
                "Workflow timeout seconds must be "
                "between 0.1 and 86400."
            )

        return normalized

    @staticmethod
    def _increment_counter(
        conn: sqlite3.Connection,
        counter_name: str,
        amount: int = 1,
    ) -> None:

        conn.execute(
            """
            INSERT INTO workflow_queue_counters (
                counter_name,
                counter_value
            )
            VALUES (?, ?)
            ON CONFLICT(counter_name)
            DO UPDATE SET
                counter_value =
                    counter_value
                    + excluded.counter_value
            """,
            (
                counter_name,
                max(int(amount), 0),
            ),
        )

    def record_timeout(
        self,
        run_id: str,
        *,
        worker_id: str,
        error: str,
    ) -> bool:

        now = _utc_now()

        with self._connect() as conn:

            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT queue_status, lease_owner,
                       timed_out_count
                FROM workflow_run_jobs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

            if (
                row is None
                or row["lease_owner"] != worker_id
                or row["queue_status"] not in {
                    "running",
                    "cancelling",
                }
            ):
                conn.rollback()
                return False

            timed_out_count = int(
                row["timed_out_count"]
            ) + 1

            conn.execute(
                """
                UPDATE workflow_run_jobs
                SET timed_out_count = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    timed_out_count,
                    error,
                    now,
                    run_id,
                ),
            )

            self._increment_counter(
                conn,
                "timeout_failures",
            )

            WorkflowRunStorage._insert_event(
                conn,
                run_id=run_id,
                sequence_no=self._next_sequence(
                    conn,
                    run_id,
                ),
                event_type="run_attempt_timed_out",
                payload={
                    "worker_id": worker_id,
                    "timed_out_count": timed_out_count,
                    "error": error,
                },
            )

            conn.commit()

        return True

    def register_worker(
        self,
        worker_id: str,
        *,
        capacity: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:

        self._register_worker_d7(
            worker_id,
            capacity=capacity,
            metadata=metadata,
        )

        now = _utc_now()

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workflow_workers
                SET control_mode = 'running',
                    control_updated_at = ?
                WHERE worker_id = ?
                """,
                (now, worker_id),
            )
            conn.commit()

    def heartbeat_worker(
        self,
        worker_id: str,
        *,
        active_count: int,
    ) -> bool:

        alive = self._heartbeat_worker_d7(
            worker_id,
            active_count=active_count,
        )

        if not alive:
            return False

        if int(active_count) == 0:
            now = _utc_now()
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE workflow_workers
                    SET control_mode = 'paused',
                        control_updated_at = ?
                    WHERE worker_id = ?
                    AND control_mode = 'draining'
                    """,
                    (now, worker_id),
                )
                conn.commit()

        return True

    def get_worker_control(
        self,
        worker_id: str,
    ) -> dict[str, Any]:

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM workflow_workers
                WHERE worker_id = ?
                """,
                (worker_id,),
            ).fetchone()

        if row is None:
            raise KeyError(
                f"Workflow worker not found: {worker_id}"
            )

        return {
            "worker_id": row["worker_id"],
            "worker_status": row["worker_status"],
            "control_mode": row["control_mode"],
            "accepting_work": (
                row["worker_status"] == "running"
                and row["control_mode"] == "running"
            ),
            "capacity": int(row["capacity"]),
            "active_count": int(row["active_count"]),
            "started_at": row["started_at"],
            "heartbeat_at": row["heartbeat_at"],
            "stopped_at": row["stopped_at"],
            "control_updated_at": (
                row["control_updated_at"]
            ),
            "metadata": json.loads(
                row["metadata_json"] or "{}"
            ),
        }

    def set_worker_control(
        self,
        worker_id: str,
        *,
        control_mode: str,
    ) -> dict[str, Any]:

        normalized = control_mode.strip().lower()

        if normalized not in {
            "running",
            "paused",
            "draining",
        }:
            raise ValueError(
                "Worker control mode must be "
                "running, paused, or draining."
            )

        now = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT worker_status
                FROM workflow_workers
                WHERE worker_id = ?
                """,
                (worker_id,),
            ).fetchone()

            if row is None:
                conn.rollback()
                raise KeyError(
                    f"Workflow worker not found: {worker_id}"
                )

            if row["worker_status"] in {
                "stopped",
                "stopping",
            }:
                conn.rollback()
                raise ValueError(
                    "Stopped or stopping workers "
                    "cannot be controlled."
                )

            conn.execute(
                """
                UPDATE workflow_workers
                SET control_mode = ?,
                    control_updated_at = ?
                WHERE worker_id = ?
                """,
                (
                    normalized,
                    now,
                    worker_id,
                ),
            )
            conn.commit()

        return self.get_worker_control(worker_id)

    def list_workers(
        self,
        *,
        stale_after_seconds: float = 90.0,
    ) -> list[dict[str, Any]]:

        workers = self._list_workers_d7(
            stale_after_seconds=stale_after_seconds,
        )

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT worker_id, control_mode,
                       control_updated_at
                FROM workflow_workers
                """
            ).fetchall()

        controls = {
            row["worker_id"]: row
            for row in rows
        }

        for worker in workers:
            row = controls.get(worker["worker_id"])
            mode = (
                row["control_mode"]
                if row is not None
                else "running"
            )
            worker["control_mode"] = mode
            worker["control_updated_at"] = (
                row["control_updated_at"]
                if row is not None
                else None
            )
            worker["accepting_work"] = (
                worker["worker_status"] == "running"
                and mode == "running"
            )

        return workers

    def queue_metrics(
        self,
        *,
        worker_stale_after_seconds: float = 90.0,
        max_queued_jobs: int | None = None,
        max_active_per_user: int | None = None,
        default_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:

        metrics = self._queue_metrics_d7(
            worker_stale_after_seconds=(
                worker_stale_after_seconds
            )
        )

        queue_limit = max(
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

        user_limit = max(
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

        timeout_default = self._normalize_timeout(
            default_timeout_seconds
            if default_timeout_seconds is not None
            else float(
                os.getenv(
                    "NOVELFORGE_WORKFLOW_TIMEOUT_SECONDS",
                    "900",
                )
            )
        )

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT counter_name, counter_value
                FROM workflow_queue_counters
                """
            ).fetchall()

        counters = {
            row["counter_name"]: int(
                row["counter_value"]
            )
            for row in rows
        }

        waiting_count = int(
            metrics["status_counts"].get("queued", 0)
        ) + int(
            metrics["status_counts"].get(
                "retry_wait",
                0,
            )
        )

        metrics.update(
            {
                "max_queued_jobs": queue_limit,
                "max_active_per_user": user_limit,
                "default_timeout_seconds": timeout_default,
                "backpressure_active": (
                    queue_limit > 0
                    and waiting_count >= queue_limit
                ),
                "queue_full_rejections": counters.get(
                    "queue_full_rejections",
                    0,
                ),
                "user_quota_rejections": counters.get(
                    "user_quota_rejections",
                    0,
                ),
                "timeout_failures": counters.get(
                    "timeout_failures",
                    0,
                ),
            }
        )

        return metrics

    _init_db_d9_base = _init_db
    _queue_metrics_d9_base = queue_metrics

    def _init_db(
        self,
    ) -> None:

        self._init_db_d9_base()

        with self._connect() as conn:

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS
                workflow_job_archive (
                    run_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    queue_status TEXT NOT NULL,
                    terminal_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_job_archive_time
                ON workflow_job_archive(
                    archived_at,
                    queue_status
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_job_archive_user
                ON workflow_job_archive(
                    user_id,
                    novel_id,
                    archived_at
                );
                """
            )

            conn.commit()

    @staticmethod
    def _d9_parse_time(
        value: str | None,
    ) -> datetime | None:

        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(
                value
            )
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    @staticmethod
    def _d9_duration_seconds(
        start: str | None,
        end: str | None,
    ) -> float | None:

        start_dt = WorkflowAsyncQueue._d9_parse_time(
            start
        )
        end_dt = WorkflowAsyncQueue._d9_parse_time(
            end
        )

        if start_dt is None or end_dt is None:
            return None

        return max(
            (end_dt - start_dt).total_seconds(),
            0.0,
        )

    def replay_dead_letters(
        self,
        run_ids: list[str],
        *,
        reset_attempts: bool = True,
        priority: int | None = None,
        max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        timeout_seconds: float | None = None,
        max_batch_size: int | None = None,
        max_queued_jobs: int | None = None,
        max_active_per_user: int | None = None,
    ) -> dict[str, Any]:

        batch_limit = max(
            int(
                max_batch_size
                if max_batch_size is not None
                else os.getenv(
                    "NOVELFORGE_WORKFLOW_DLQ_REPLAY_BATCH_MAX",
                    "100",
                )
            ),
            1,
        )

        ordered_ids: list[str] = []
        seen: set[str] = set()

        for raw_run_id in run_ids:
            run_id = str(raw_run_id).strip()
            if run_id and run_id not in seen:
                ordered_ids.append(run_id)
                seen.add(run_id)

        if not ordered_ids:
            raise ValueError(
                "At least one workflow run ID is required."
            )

        if len(ordered_ids) > batch_limit:
            raise ValueError(
                "Dead-letter replay batch exceeds "
                f"the configured limit of {batch_limit}."
            )

        queue_limit = max(
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

        user_limit = max(
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

        replayed: list[str] = []
        skipped: list[dict[str, str]] = []

        for run_id in ordered_ids:

            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT jobs.queue_status,
                           runs.user_id
                    FROM workflow_run_jobs AS jobs
                    JOIN workflow_runs AS runs
                      ON runs.run_id = jobs.run_id
                    WHERE jobs.run_id = ?
                    """,
                    (run_id,),
                ).fetchone()

                if row is None:
                    skipped.append(
                        {
                            "run_id": run_id,
                            "reason": "not_found",
                        }
                    )
                    continue

                if row["queue_status"] != "dead_letter":
                    skipped.append(
                        {
                            "run_id": run_id,
                            "reason": "not_dead_letter",
                        }
                    )
                    continue

                if queue_limit > 0:
                    waiting = int(
                        conn.execute(
                            """
                            SELECT COUNT(*) AS count
                            FROM workflow_run_jobs
                            WHERE queue_status IN (
                                'queued',
                                'retry_wait'
                            )
                            """
                        ).fetchone()["count"]
                    )

                    if waiting >= queue_limit:
                        skipped.append(
                            {
                                "run_id": run_id,
                                "reason": "queue_full",
                            }
                        )
                        continue

                if user_limit > 0:
                    active = int(
                        conn.execute(
                            """
                            SELECT COUNT(*) AS count
                            FROM workflow_run_jobs AS jobs
                            JOIN workflow_runs AS runs
                              ON runs.run_id = jobs.run_id
                            WHERE runs.user_id = ?
                              AND jobs.queue_status IN (
                                  'queued',
                                  'retry_wait',
                                  'running',
                                  'cancelling'
                              )
                            """,
                            (row["user_id"],),
                        ).fetchone()["count"]
                    )

                    if active >= user_limit:
                        skipped.append(
                            {
                                "run_id": run_id,
                                "reason": "user_quota_exceeded",
                            }
                        )
                        continue

            self.retry_run(
                run_id,
                reset_attempts=reset_attempts,
                priority=priority,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
                timeout_seconds=timeout_seconds,
            )

            replayed.append(run_id)

        if replayed:
            with self._connect() as conn:
                self._increment_counter(
                    conn,
                    "dlq_replayed",
                    len(replayed),
                )
                conn.commit()

        return {
            "requested_count": len(ordered_ids),
            "replayed_count": len(replayed),
            "skipped_count": len(skipped),
            "replayed_run_ids": replayed,
            "skipped": skipped,
        }

    def archive_terminal_jobs(
        self,
        *,
        older_than_seconds: float = 604800.0,
        limit: int = 500,
        include_dead_letter: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:

        age = float(older_than_seconds)
        if not 0.0 <= age <= 315360000.0:
            raise ValueError(
                "Archive age must be between 0 and 315360000 seconds."
            )

        normalized_limit = min(
            max(int(limit), 1),
            5000,
        )

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(seconds=age)
        ).isoformat()

        statuses = [
            "completed",
            "cancelled",
            "failed",
        ]
        if include_dead_letter:
            statuses.append("dead_letter")

        placeholders = ",".join(
            "?" for _ in statuses
        )

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT jobs.*,
                       runs.user_id,
                       runs.novel_id,
                       runs.completed_at
                FROM workflow_run_jobs AS jobs
                JOIN workflow_runs AS runs
                  ON runs.run_id = jobs.run_id
                WHERE jobs.queue_status IN (
                    {placeholders}
                )
                  AND COALESCE(
                      runs.completed_at,
                      jobs.updated_at
                  ) <= ?
                ORDER BY COALESCE(
                    runs.completed_at,
                    jobs.updated_at
                ) ASC
                LIMIT ?
                """,
                (
                    *statuses,
                    cutoff,
                    normalized_limit,
                ),
            ).fetchall()

        candidate_ids = [
            row["run_id"] for row in rows
        ]

        if dry_run or not rows:
            return {
                "dry_run": bool(dry_run),
                "candidate_count": len(rows),
                "archived_count": 0,
                "run_ids": candidate_ids,
            }

        archived: list[str] = []
        archived_at = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            for row in rows:
                run_id = row["run_id"]
                terminal_at = (
                    row["completed_at"]
                    or row["updated_at"]
                )
                snapshot = dict(row)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO
                    workflow_job_archive (
                        run_id,
                        user_id,
                        novel_id,
                        queue_status,
                        terminal_at,
                        archived_at,
                        snapshot_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        row["user_id"],
                        row["novel_id"],
                        row["queue_status"],
                        terminal_at,
                        archived_at,
                        _json_dumps(snapshot),
                    ),
                )

                WorkflowRunStorage._insert_event(
                    conn,
                    run_id=run_id,
                    sequence_no=self._next_sequence(
                        conn,
                        run_id,
                    ),
                    event_type="queue_job_archived",
                    payload={
                        "queue_status": row["queue_status"],
                        "terminal_at": terminal_at,
                        "archived_at": archived_at,
                    },
                )

                deleted = conn.execute(
                    """
                    DELETE FROM workflow_run_jobs
                    WHERE run_id = ?
                      AND queue_status = ?
                    """,
                    (
                        run_id,
                        row["queue_status"],
                    ),
                ).rowcount

                if deleted:
                    archived.append(run_id)

            if archived:
                self._increment_counter(
                    conn,
                    "archived_jobs",
                    len(archived),
                )

            conn.commit()

        return {
            "dry_run": False,
            "candidate_count": len(rows),
            "archived_count": len(archived),
            "run_ids": archived,
        }

    def list_archived_jobs(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        normalized_limit = min(
            max(int(limit), 1),
            500,
        )

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id,
                       user_id,
                       novel_id,
                       queue_status,
                       terminal_at,
                       archived_at
                FROM workflow_job_archive
                ORDER BY archived_at DESC,
                         terminal_at DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def worker_cluster_health(
        self,
        *,
        stale_after_seconds: float = 90.0,
    ) -> dict[str, Any]:

        workers = self.list_workers(
            stale_after_seconds=stale_after_seconds
        )

        total_workers = len(workers)
        running_workers = sum(
            1 for item in workers
            if item["worker_status"] == "running"
        )
        stale_workers = sum(
            1 for item in workers
            if item["worker_status"] == "stale"
        )
        paused_workers = sum(
            1 for item in workers
            if item.get("control_mode") == "paused"
        )
        draining_workers = sum(
            1 for item in workers
            if item.get("control_mode") == "draining"
        )
        accepting_workers = sum(
            1 for item in workers
            if item.get("accepting_work") is True
        )

        total_capacity = sum(
            int(item.get("capacity", 0))
            for item in workers
            if item["worker_status"] == "running"
        )
        active_count = sum(
            int(item.get("active_count", 0))
            for item in workers
            if item["worker_status"] == "running"
        )
        available_slots = max(
            total_capacity - active_count,
            0,
        )

        with self._connect() as conn:
            ready_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM workflow_run_jobs
                    WHERE queue_status IN (
                        'queued',
                        'retry_wait'
                    )
                      AND available_at <= ?
                    """,
                    (_utc_now(),),
                ).fetchone()["count"]
            )

        if running_workers == 0:
            health_status = "unavailable"
        elif accepting_workers == 0:
            health_status = "degraded"
        else:
            health_status = "healthy"

        utilization = (
            float(active_count) / float(total_capacity)
            if total_capacity > 0
            else 0.0
        )

        return {
            "health_status": health_status,
            "total_workers": total_workers,
            "running_workers": running_workers,
            "stale_workers": stale_workers,
            "paused_workers": paused_workers,
            "draining_workers": draining_workers,
            "accepting_workers": accepting_workers,
            "total_capacity": total_capacity,
            "active_count": active_count,
            "available_slots": available_slots,
            "utilization": utilization,
            "ready_count": ready_count,
        }

    def queue_metrics(
        self,
        *,
        worker_stale_after_seconds: float = 90.0,
        max_queued_jobs: int | None = None,
        max_active_per_user: int | None = None,
        default_timeout_seconds: float | None = None,
        window_seconds: float = 300.0,
    ) -> dict[str, Any]:

        metrics = self._queue_metrics_d9_base(
            worker_stale_after_seconds=(
                worker_stale_after_seconds
            ),
            max_queued_jobs=max_queued_jobs,
            max_active_per_user=max_active_per_user,
            default_timeout_seconds=(
                default_timeout_seconds
            ),
        )

        window = min(
            max(float(window_seconds), 1.0),
            86400.0,
        )
        now_dt = datetime.now(timezone.utc)
        cutoff = (
            now_dt - timedelta(seconds=window)
        ).isoformat()
        now = now_dt.isoformat()

        with self._connect() as conn:
            terminal_rows = conn.execute(
                """
                SELECT queue_status,
                       queued_at,
                       claimed_at,
                       updated_at
                FROM workflow_run_jobs
                WHERE queue_status IN (
                    'completed',
                    'cancelled',
                    'failed',
                    'dead_letter'
                )
                  AND updated_at >= ?
                """,
                (cutoff,),
            ).fetchall()

            claim_rows = conn.execute(
                """
                SELECT queued_at,
                       claimed_at,
                       updated_at,
                       queue_status
                FROM workflow_run_jobs
                WHERE claimed_at IS NOT NULL
                  AND claimed_at >= ?
                """,
                (cutoff,),
            ).fetchall()

            oldest_ready = conn.execute(
                """
                SELECT MIN(queued_at) AS oldest
                FROM workflow_run_jobs
                WHERE queue_status IN (
                    'queued',
                    'retry_wait'
                )
                  AND available_at <= ?
                """,
                (now,),
            ).fetchone()["oldest"]

            archive_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM workflow_job_archive
                    """
                ).fetchone()["count"]
            )

            counter_rows = conn.execute(
                """
                SELECT counter_name, counter_value
                FROM workflow_queue_counters
                WHERE counter_name IN (
                    'dlq_replayed',
                    'archived_jobs'
                )
                """
            ).fetchall()

        status_window: dict[str, int] = {}
        for row in terminal_rows:
            status_window[row["queue_status"]] = (
                status_window.get(row["queue_status"], 0)
                + 1
            )

        terminal_count = sum(status_window.values())
        completed_count = status_window.get("completed", 0)

        queue_latencies = [
            value
            for value in (
                self._d9_duration_seconds(
                    row["queued_at"],
                    row["claimed_at"],
                )
                for row in claim_rows
            )
            if value is not None
        ]

        execution_durations = [
            value
            for value in (
                self._d9_duration_seconds(
                    row["claimed_at"],
                    row["updated_at"],
                )
                for row in terminal_rows
                if row["claimed_at"] is not None
            )
            if value is not None
        ]

        oldest_ready_age = None
        oldest_dt = self._d9_parse_time(oldest_ready)
        if oldest_dt is not None:
            oldest_ready_age = max(
                (now_dt - oldest_dt).total_seconds(),
                0.0,
            )

        counters = {
            row["counter_name"]: int(row["counter_value"])
            for row in counter_rows
        }

        per_minute_factor = 60.0 / window

        metrics.update(
            {
                "observation_window_seconds": window,
                "terminal_in_window": terminal_count,
                "completed_in_window": completed_count,
                "failed_in_window": status_window.get("failed", 0),
                "dead_lettered_in_window": status_window.get("dead_letter", 0),
                "cancelled_in_window": status_window.get("cancelled", 0),
                "throughput_per_minute": terminal_count * per_minute_factor,
                "success_throughput_per_minute": completed_count * per_minute_factor,
                "queue_latency_samples": len(queue_latencies),
                "queue_latency_seconds_average": (
                    sum(queue_latencies) / len(queue_latencies)
                    if queue_latencies else None
                ),
                "queue_latency_seconds_max": (
                    max(queue_latencies)
                    if queue_latencies else None
                ),
                "execution_duration_samples": len(execution_durations),
                "execution_duration_seconds_average": (
                    sum(execution_durations) / len(execution_durations)
                    if execution_durations else None
                ),
                "execution_duration_seconds_max": (
                    max(execution_durations)
                    if execution_durations else None
                ),
                "oldest_ready_age_seconds": oldest_ready_age,
                "archived_job_count": archive_count,
                "dlq_replayed_total": counters.get("dlq_replayed", 0),
                "archived_jobs_total": counters.get("archived_jobs", 0),
            }
        )

        return metrics
