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

    def enqueue(
        self,
        request: ChapterWorkflowRequest,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[
        str,
        bool,
    ]:

        normalized_key = (
            self._normalize_key(
                idempotency_key
            )
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
                    runs.request_json
                FROM workflow_run_jobs
                    AS jobs
                JOIN workflow_runs
                    AS runs
                    ON runs.run_id =
                        jobs.run_id
                WHERE jobs.queue_status =
                    'queued'
                ORDER BY jobs.queued_at ASC
                LIMIT 1
                """
            ).fetchone()

            if row is None:

                conn.commit()

                return None

            run_id = row["run_id"]

            updated = conn.execute(
                """
                UPDATE workflow_run_jobs
                SET
                    queue_status =
                        'running',
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
                AND queue_status = 'queued'
                """,
                (
                    worker_id,
                    lease_expires_at,
                    now,
                    now,
                    now,
                    run_id,
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
                event_type="run_claimed",
                payload={
                    "worker_id": worker_id,
                    "lease_expires_at": (
                        lease_expires_at
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

            if queue_status == "queued":

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
