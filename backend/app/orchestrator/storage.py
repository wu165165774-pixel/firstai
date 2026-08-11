from __future__ import annotations

import json
import os
import sqlite3
import uuid

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    NovelOrchestrationDetail,
    NovelOrchestrationEvent,
    NovelOrchestrationStep,
    NovelOrchestrationSummary,
    OrchestrationQueuePolicy,
    OrchestrationWorkflowPolicy,
)


class NovelOrchestrationNotFoundError(LookupError):
    pass


class NovelOrchestrationConflictError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class NovelOrchestrationStorage:
    """SQLite state machine storage colocated with Workflow Runs."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv(
            "NOVELFORGE_WORKFLOW_DB_PATH",
            "/app/data/workflow_runs.db",
        )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS novel_orchestrations (
                    orchestration_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    current_sequence_no INTEGER,
                    total_chapters INTEGER NOT NULL,
                    accepted_chapters INTEGER NOT NULL DEFAULT 0,
                    selection_json TEXT NOT NULL DEFAULT '{}',
                    workflow_policy_json TEXT NOT NULL,
                    queue_policy_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    idempotency_key TEXT UNIQUE,
                    paused_from_status TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_novel_orchestrations_list
                ON novel_orchestrations(novel_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS novel_orchestration_steps (
                    orchestration_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    chapter_plan_id TEXT NOT NULL,
                    chapter_plan_revision INTEGER NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    chapter_title TEXT NOT NULL,
                    arc_id TEXT NOT NULL,
                    arc_revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    workflow_run_id TEXT,
                    workflow_attempt INTEGER NOT NULL DEFAULT 0,
                    manuscript_chapter_id TEXT,
                    candidate_revision INTEGER,
                    accepted_revision INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(orchestration_id, sequence_no),
                    UNIQUE(orchestration_id, chapter_plan_id),
                    FOREIGN KEY(orchestration_id)
                        REFERENCES novel_orchestrations(orchestration_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_novel_orchestration_steps_run
                ON novel_orchestration_steps(workflow_run_id);

                CREATE TABLE IF NOT EXISTS novel_orchestration_events (
                    event_id TEXT PRIMARY KEY,
                    orchestration_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    chapter_sequence_no INTEGER,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(orchestration_id, sequence_no),
                    FOREIGN KEY(orchestration_id)
                        REFERENCES novel_orchestrations(orchestration_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_novel_orchestration_events
                ON novel_orchestration_events(orchestration_id, sequence_no);
                """
            )
            conn.commit()

    @staticmethod
    def _summary_from_row(row: sqlite3.Row) -> NovelOrchestrationSummary:
        return NovelOrchestrationSummary(
            orchestration_id=row["orchestration_id"],
            novel_id=row["novel_id"],
            user_id=row["user_id"],
            status=row["status"],
            revision=int(row["revision"]),
            current_sequence_no=(
                int(row["current_sequence_no"])
                if row["current_sequence_no"] is not None
                else None
            ),
            total_chapters=int(row["total_chapters"]),
            accepted_chapters=int(row["accepted_chapters"]),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _step_from_row(row: sqlite3.Row) -> NovelOrchestrationStep:
        return NovelOrchestrationStep(
            orchestration_id=row["orchestration_id"],
            sequence_no=int(row["sequence_no"]),
            chapter_plan_id=row["chapter_plan_id"],
            chapter_plan_revision=int(row["chapter_plan_revision"]),
            chapter_number=int(row["chapter_number"]),
            chapter_title=row["chapter_title"],
            arc_id=row["arc_id"],
            arc_revision=int(row["arc_revision"]),
            status=row["status"],
            workflow_run_id=row["workflow_run_id"],
            workflow_attempt=int(row["workflow_attempt"]),
            manuscript_chapter_id=row["manuscript_chapter_id"],
            candidate_revision=(
                int(row["candidate_revision"])
                if row["candidate_revision"] is not None
                else None
            ),
            accepted_revision=(
                int(row["accepted_revision"])
                if row["accepted_revision"] is not None
                else None
            ),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> NovelOrchestrationEvent:
        return NovelOrchestrationEvent(
            event_id=row["event_id"],
            orchestration_id=row["orchestration_id"],
            sequence_no=int(row["sequence_no"]),
            event_type=row["event_type"],
            chapter_sequence_no=(
                int(row["chapter_sequence_no"])
                if row["chapter_sequence_no"] is not None
                else None
            ),
            payload=_json_load(row["payload_json"], {}),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row(
        conn: sqlite3.Connection,
        novel_id: str,
        orchestration_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT * FROM novel_orchestrations
            WHERE novel_id = ? AND orchestration_id = ?
            """,
            (novel_id, orchestration_id),
        ).fetchone()
        if row is None:
            raise NovelOrchestrationNotFoundError(
                "Novel Orchestration not found: "
                f"{novel_id}:{orchestration_id}"
            )
        return row

    @staticmethod
    def _assert_revision(row: sqlite3.Row, expected_revision: int) -> None:
        current = int(row["revision"])
        if current != expected_revision:
            raise NovelOrchestrationConflictError(
                "Novel Orchestration revision conflict: "
                f"expected={expected_revision}, current={current}."
            )

    @staticmethod
    def _next_event_sequence(
        conn: sqlite3.Connection,
        orchestration_id: str,
    ) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence_no), -1) AS value
            FROM novel_orchestration_events
            WHERE orchestration_id = ?
            """,
            (orchestration_id,),
        ).fetchone()
        return int(row["value"]) + 1

    @classmethod
    def _insert_event(
        cls,
        conn: sqlite3.Connection,
        orchestration_id: str,
        event_type: str,
        *,
        chapter_sequence_no: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO novel_orchestration_events (
                event_id,
                orchestration_id,
                sequence_no,
                event_type,
                chapter_sequence_no,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                orchestration_id,
                cls._next_event_sequence(conn, orchestration_id),
                event_type,
                chapter_sequence_no,
                _json_dump(payload or {}),
                _utc_now(),
            ),
        )

    @classmethod
    def _detail_from_conn(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> NovelOrchestrationDetail:
        steps = conn.execute(
            """
            SELECT * FROM novel_orchestration_steps
            WHERE orchestration_id = ?
            ORDER BY sequence_no ASC
            """,
            (row["orchestration_id"],),
        ).fetchall()
        events = conn.execute(
            """
            SELECT * FROM novel_orchestration_events
            WHERE orchestration_id = ?
            ORDER BY sequence_no ASC
            """,
            (row["orchestration_id"],),
        ).fetchall()
        summary = cls._summary_from_row(row)
        return NovelOrchestrationDetail(
            **summary.model_dump(),
            selection=_json_load(row["selection_json"], {}),
            workflow=OrchestrationWorkflowPolicy.model_validate(
                _json_load(row["workflow_policy_json"], {})
            ),
            queue=OrchestrationQueuePolicy.model_validate(
                _json_load(row["queue_policy_json"], {})
            ),
            metadata=_json_load(row["metadata_json"], {}),
            paused_from_status=row["paused_from_status"],
            steps=[cls._step_from_row(item) for item in steps],
            events=[cls._event_from_row(item) for item in events],
        )

    def create(
        self,
        *,
        novel_id: str,
        user_id: str,
        selection: dict[str, Any],
        workflow_policy: OrchestrationWorkflowPolicy,
        queue_policy: OrchestrationQueuePolicy,
        metadata: dict[str, Any],
        steps: list[dict[str, Any]],
        idempotency_key: str | None,
    ) -> tuple[NovelOrchestrationDetail, bool]:
        normalized_key = (idempotency_key or "").strip() or None
        if normalized_key is not None and len(normalized_key) > 128:
            raise ValueError("Idempotency key must not exceed 128 characters.")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if normalized_key is not None:
                existing = conn.execute(
                    """
                    SELECT * FROM novel_orchestrations
                    WHERE idempotency_key = ?
                    """,
                    (normalized_key,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["novel_id"] != novel_id
                        or existing["user_id"] != user_id
                    ):
                        raise NovelOrchestrationConflictError(
                            "Idempotency key belongs to another Novel "
                            "Orchestration owner."
                        )
                    detail = self._detail_from_conn(conn, existing)
                    conn.commit()
                    return detail, True

            orchestration_id = str(uuid.uuid4())
            now = _utc_now()
            accepted = sum(
                1 for item in steps if item["status"] == "accepted"
            )
            pending = next(
                (
                    int(item["sequence_no"])
                    for item in steps
                    if item["status"] == "pending"
                ),
                None,
            )
            status = "ready" if pending is not None else "completed"
            completed_at = now if status == "completed" else None
            conn.execute(
                """
                INSERT INTO novel_orchestrations (
                    orchestration_id,
                    novel_id,
                    user_id,
                    status,
                    revision,
                    current_sequence_no,
                    total_chapters,
                    accepted_chapters,
                    selection_json,
                    workflow_policy_json,
                    queue_policy_json,
                    metadata_json,
                    idempotency_key,
                    created_at,
                    updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    orchestration_id,
                    novel_id,
                    user_id,
                    status,
                    pending,
                    len(steps),
                    accepted,
                    _json_dump(selection),
                    _json_dump(workflow_policy.model_dump(mode="json")),
                    _json_dump(queue_policy.model_dump(mode="json")),
                    _json_dump(metadata),
                    normalized_key,
                    now,
                    now,
                    completed_at,
                ),
            )
            for item in steps:
                conn.execute(
                    """
                    INSERT INTO novel_orchestration_steps (
                        orchestration_id,
                        sequence_no,
                        chapter_plan_id,
                        chapter_plan_revision,
                        chapter_number,
                        chapter_title,
                        arc_id,
                        arc_revision,
                        status,
                        manuscript_chapter_id,
                        accepted_revision,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        orchestration_id,
                        int(item["sequence_no"]),
                        item["chapter_plan_id"],
                        int(item["chapter_plan_revision"]),
                        int(item["chapter_number"]),
                        item["chapter_title"],
                        item["arc_id"],
                        int(item["arc_revision"]),
                        item["status"],
                        item.get("manuscript_chapter_id"),
                        item.get("accepted_revision"),
                        now,
                        now,
                    ),
                )
            self._insert_event(
                conn,
                orchestration_id,
                "orchestration_created",
                payload={
                    "total_chapters": len(steps),
                    "accepted_chapters": accepted,
                    "current_sequence_no": pending,
                    "status": status,
                },
            )
            row = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, row)
            conn.commit()
        return detail, False

    def get(
        self,
        novel_id: str,
        orchestration_id: str,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            row = self._row(conn, novel_id, orchestration_id)
            return self._detail_from_conn(conn, row)

    def list(
        self,
        novel_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NovelOrchestrationSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM novel_orchestrations
                WHERE novel_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (novel_id, limit, offset),
            ).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def attach_workflow(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        workflow_run_id: str,
        workflow_attempt: int,
        retry: bool = False,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, novel_id, orchestration_id)
            self._assert_revision(row, expected_revision)
            sequence = row["current_sequence_no"]
            if sequence is None:
                raise NovelOrchestrationConflictError(
                    "Completed orchestration has no current chapter."
                )
            now = _utc_now()
            conn.execute(
                """
                UPDATE novel_orchestration_steps
                SET status = 'workflow_queued',
                    workflow_run_id = ?,
                    workflow_attempt = ?,
                    manuscript_chapter_id = NULL,
                    candidate_revision = NULL,
                    error = NULL,
                    updated_at = ?
                WHERE orchestration_id = ? AND sequence_no = ?
                """,
                (
                    workflow_run_id,
                    workflow_attempt,
                    now,
                    orchestration_id,
                    sequence,
                ),
            )
            conn.execute(
                """
                UPDATE novel_orchestrations
                SET status = 'waiting_for_workflow',
                    revision = revision + 1,
                    error = NULL,
                    updated_at = ?
                WHERE orchestration_id = ?
                """,
                (now, orchestration_id),
            )
            self._insert_event(
                conn,
                orchestration_id,
                (
                    "chapter_workflow_retried"
                    if retry
                    else "chapter_workflow_queued"
                ),
                chapter_sequence_no=int(sequence),
                payload={
                    "workflow_run_id": workflow_run_id,
                    "workflow_attempt": workflow_attempt,
                },
            )
            updated = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, updated)
            conn.commit()
        return detail

    def mark_candidate(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        manuscript_chapter_id: str,
        candidate_revision: int,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, novel_id, orchestration_id)
            self._assert_revision(row, expected_revision)
            sequence = row["current_sequence_no"]
            if sequence is None:
                raise NovelOrchestrationConflictError(
                    "Completed orchestration has no current chapter."
                )
            now = _utc_now()
            conn.execute(
                """
                UPDATE novel_orchestration_steps
                SET status = 'candidate_ready',
                    manuscript_chapter_id = ?,
                    candidate_revision = ?,
                    error = NULL,
                    updated_at = ?
                WHERE orchestration_id = ? AND sequence_no = ?
                """,
                (
                    manuscript_chapter_id,
                    candidate_revision,
                    now,
                    orchestration_id,
                    sequence,
                ),
            )
            conn.execute(
                """
                UPDATE novel_orchestrations
                SET status = 'waiting_for_acceptance',
                    revision = revision + 1,
                    error = NULL,
                    updated_at = ?
                WHERE orchestration_id = ?
                """,
                (now, orchestration_id),
            )
            self._insert_event(
                conn,
                orchestration_id,
                "chapter_candidate_imported",
                chapter_sequence_no=int(sequence),
                payload={
                    "manuscript_chapter_id": manuscript_chapter_id,
                    "candidate_revision": candidate_revision,
                },
            )
            updated = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, updated)
            conn.commit()
        return detail

    def mark_failed(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        error: str,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, novel_id, orchestration_id)
            self._assert_revision(row, expected_revision)
            sequence = row["current_sequence_no"]
            now = _utc_now()
            if sequence is not None:
                conn.execute(
                    """
                    UPDATE novel_orchestration_steps
                    SET status = 'failed', error = ?, updated_at = ?
                    WHERE orchestration_id = ? AND sequence_no = ?
                    """,
                    (error, now, orchestration_id, sequence),
                )
            conn.execute(
                """
                UPDATE novel_orchestrations
                SET status = 'failed',
                    revision = revision + 1,
                    error = ?,
                    updated_at = ?
                WHERE orchestration_id = ?
                """,
                (error, now, orchestration_id),
            )
            self._insert_event(
                conn,
                orchestration_id,
                "orchestration_failed",
                chapter_sequence_no=(int(sequence) if sequence else None),
                payload={"error": error},
            )
            updated = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, updated)
            conn.commit()
        return detail

    def mark_accepted(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
        accepted_revision: int,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, novel_id, orchestration_id)
            self._assert_revision(row, expected_revision)
            sequence = row["current_sequence_no"]
            if sequence is None:
                raise NovelOrchestrationConflictError(
                    "Completed orchestration has no current chapter."
                )
            now = _utc_now()
            conn.execute(
                """
                UPDATE novel_orchestration_steps
                SET status = 'accepted',
                    accepted_revision = ?,
                    error = NULL,
                    updated_at = ?
                WHERE orchestration_id = ? AND sequence_no = ?
                """,
                (accepted_revision, now, orchestration_id, sequence),
            )
            next_row = conn.execute(
                """
                SELECT MIN(sequence_no) AS sequence_no
                FROM novel_orchestration_steps
                WHERE orchestration_id = ? AND status = 'pending'
                """,
                (orchestration_id,),
            ).fetchone()
            next_sequence = next_row["sequence_no"]
            accepted_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS value
                    FROM novel_orchestration_steps
                    WHERE orchestration_id = ? AND status = 'accepted'
                    """,
                    (orchestration_id,),
                ).fetchone()["value"]
            )
            status = "ready" if next_sequence is not None else "completed"
            conn.execute(
                """
                UPDATE novel_orchestrations
                SET status = ?,
                    revision = revision + 1,
                    current_sequence_no = ?,
                    accepted_chapters = ?,
                    error = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE orchestration_id = ?
                """,
                (
                    status,
                    next_sequence,
                    accepted_count,
                    now,
                    now if status == "completed" else None,
                    orchestration_id,
                ),
            )
            self._insert_event(
                conn,
                orchestration_id,
                "chapter_accepted",
                chapter_sequence_no=int(sequence),
                payload={
                    "accepted_revision": accepted_revision,
                    "next_sequence_no": next_sequence,
                },
            )
            if status == "completed":
                self._insert_event(
                    conn,
                    orchestration_id,
                    "orchestration_completed",
                    payload={"accepted_chapters": accepted_count},
                )
            updated = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, updated)
            conn.commit()
        return detail

    def pause(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, novel_id, orchestration_id)
            self._assert_revision(row, expected_revision)
            if row["status"] == "paused":
                detail = self._detail_from_conn(conn, row)
                conn.commit()
                return detail
            if row["status"] == "completed":
                raise NovelOrchestrationConflictError(
                    "Completed orchestration cannot be paused."
                )
            now = _utc_now()
            conn.execute(
                """
                UPDATE novel_orchestrations
                SET status = 'paused',
                    paused_from_status = ?,
                    revision = revision + 1,
                    updated_at = ?
                WHERE orchestration_id = ?
                """,
                (row["status"], now, orchestration_id),
            )
            self._insert_event(
                conn,
                orchestration_id,
                "orchestration_paused",
                chapter_sequence_no=row["current_sequence_no"],
                payload={"paused_from_status": row["status"]},
            )
            updated = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, updated)
            conn.commit()
        return detail

    def resume(
        self,
        novel_id: str,
        orchestration_id: str,
        *,
        expected_revision: int,
    ) -> NovelOrchestrationDetail:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, novel_id, orchestration_id)
            self._assert_revision(row, expected_revision)
            if row["status"] != "paused":
                raise NovelOrchestrationConflictError(
                    "Only a paused orchestration can be resumed."
                )
            restored = row["paused_from_status"] or "ready"
            if restored in {"paused", "completed"}:
                restored = "ready"
            now = _utc_now()
            conn.execute(
                """
                UPDATE novel_orchestrations
                SET status = ?,
                    paused_from_status = NULL,
                    revision = revision + 1,
                    updated_at = ?
                WHERE orchestration_id = ?
                """,
                (restored, now, orchestration_id),
            )
            self._insert_event(
                conn,
                orchestration_id,
                "orchestration_resumed",
                chapter_sequence_no=row["current_sequence_no"],
                payload={"restored_status": restored},
            )
            updated = self._row(conn, novel_id, orchestration_id)
            detail = self._detail_from_conn(conn, updated)
            conn.commit()
        return detail
