from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from typing import Any

from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResult,
)


def _utc_now() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def _json_dumps(
    value: Any,
) -> str:

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )


class WorkflowRunStorage:
    """
    SQLite storage for workflow runs,
    events, and chapter versions.
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
                workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    root_run_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    user_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    workflow_type TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    workflow_status TEXT,
                    quality_gate_passed INTEGER
                        NOT NULL DEFAULT 0,
                    resumable INTEGER
                        NOT NULL DEFAULT 0,
                    revision_rounds INTEGER
                        NOT NULL DEFAULT 0,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    latest_content TEXT
                        NOT NULL DEFAULT '',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS
                workflow_run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    round_index INTEGER,
                    attempt_index INTEGER,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        run_id,
                        sequence_no
                    ),
                    FOREIGN KEY(run_id)
                        REFERENCES workflow_runs(
                            run_id
                        )
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS
                workflow_chapter_versions (
                    version_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    version_index INTEGER
                        NOT NULL,
                    source_stage TEXT NOT NULL,
                    round_index INTEGER
                        NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        run_id,
                        version_index
                    ),
                    FOREIGN KEY(run_id)
                        REFERENCES workflow_runs(
                            run_id
                        )
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_runs_user_novel
                ON workflow_runs(
                    user_id,
                    novel_id,
                    created_at DESC
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_runs_root
                ON workflow_runs(
                    root_run_id,
                    created_at ASC
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_events_run
                ON workflow_run_events(
                    run_id,
                    sequence_no
                );

                CREATE INDEX IF NOT EXISTS
                idx_workflow_versions_run
                ON workflow_chapter_versions(
                    run_id,
                    version_index
                );
                """
            )

            conn.commit()

    @staticmethod
    def _run_row_to_dict(
        row: sqlite3.Row,
    ) -> dict[str, Any]:

        latest_content = (
            row["latest_content"]
            or ""
        )

        return {
            "run_id": row["run_id"],
            "root_run_id": (
                row["root_run_id"]
            ),
            "parent_run_id": (
                row["parent_run_id"]
            ),
            "user_id": row["user_id"],
            "novel_id": row["novel_id"],
            "workflow_type": (
                row["workflow_type"]
            ),
            "execution_status": (
                row["execution_status"]
            ),
            "workflow_status": (
                row["workflow_status"]
            ),
            "quality_gate_passed": bool(
                row[
                    "quality_gate_passed"
                ]
            ),
            "resumable": bool(
                row["resumable"]
            ),
            "revision_rounds": int(
                row["revision_rounds"]
                or 0
            ),
            "latest_content_length": len(
                latest_content
            ),
            "latest_content": (
                latest_content
            ),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": (
                row["completed_at"]
            ),
            "request": json.loads(
                row["request_json"]
            ),
            "result": (
                json.loads(
                    row["result_json"]
                )
                if row["result_json"]
                else None
            ),
        }

    def create_run(
        self,
        request: ChapterWorkflowRequest,
        *,
        parent_run_id: str | None = None,
        root_run_id: str | None = None,
    ) -> dict[str, Any]:

        run_id = str(
            uuid.uuid4()
        )

        resolved_root = (
            root_run_id
            or run_id
        )

        now = _utc_now()

        request_payload = (
            request.model_dump(
                mode="json"
            )
        )

        with self._connect() as conn:

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
                    request_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    'running',
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    run_id,
                    resolved_root,
                    parent_run_id,
                    request.user_id,
                    request.novel_id,
                    "chapter_production",
                    _json_dumps(
                        request_payload
                    ),
                    now,
                    now,
                ),
            )

            self._insert_event(
                conn,
                run_id=run_id,
                sequence_no=0,
                event_type=(
                    "run_started"
                ),
                payload={
                    "parent_run_id": (
                        parent_run_id
                    ),
                    "root_run_id": (
                        resolved_root
                    ),
                },
            )

            conn.commit()

        return self.get_run(
            run_id
        )

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *,
        run_id: str,
        sequence_no: int,
        event_type: str,
        payload: dict[str, Any],
        stage: str | None = None,
        round_index: int | None = None,
        attempt_index: int | None = None,
    ) -> None:

        conn.execute(
            """
            INSERT INTO workflow_run_events (
                event_id,
                run_id,
                sequence_no,
                event_type,
                stage,
                round_index,
                attempt_index,
                payload_json,
                created_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                str(
                    uuid.uuid4()
                ),
                run_id,
                sequence_no,
                event_type,
                stage,
                round_index,
                attempt_index,
                _json_dumps(
                    payload
                ),
                _utc_now(),
            ),
        )

    @staticmethod
    def _insert_version(
        conn: sqlite3.Connection,
        *,
        run_id: str,
        version_index: int,
        source_stage: str,
        round_index: int,
        content: str,
    ) -> None:

        content_hash = (
            hashlib.sha256(
                content.encode(
                    "utf-8"
                )
            ).hexdigest()
        )

        conn.execute(
            """
            INSERT INTO
            workflow_chapter_versions (
                version_id,
                run_id,
                version_index,
                source_stage,
                round_index,
                content,
                content_hash,
                created_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                str(
                    uuid.uuid4()
                ),
                run_id,
                version_index,
                source_stage,
                round_index,
                content,
                content_hash,
                _utc_now(),
            ),
        )

    def finalize_run(
        self,
        run_id: str,
        result: ChapterWorkflowResult,
    ) -> dict[str, Any]:

        now = _utc_now()

        result_payload = (
            result.model_dump(
                mode="json"
            )
        )

        if result.quality_gate_passed:

            execution_status = (
                "succeeded"
            )

            resumable = False

        elif result.final_content.strip():

            execution_status = (
                "resumable"
            )

            resumable = True

        else:

            execution_status = (
                "failed"
            )

            resumable = False

        with self._connect() as conn:

            existing = conn.execute(
                """
                SELECT run_id
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            if existing is None:

                raise KeyError(
                    f"Workflow run not found: "
                    f"{run_id}"
                )

            conn.execute(
                """
                DELETE FROM
                workflow_run_events
                WHERE run_id = ?
                AND sequence_no > 0
                """,
                (
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

            sequence_no = 1
            version_index = 0

            for step in (
                result.workflow_steps
            ):

                step_payload = (
                    step.model_dump(
                        mode="json"
                    )
                )

                self._insert_event(
                    conn,
                    run_id=run_id,
                    sequence_no=(
                        sequence_no
                    ),
                    event_type=(
                        "workflow_step"
                    ),
                    stage=step.stage,
                    round_index=(
                        step.round_index
                    ),
                    attempt_index=(
                        step.attempt_index
                    ),
                    payload=step_payload,
                )

                sequence_no += 1

                if (
                    step.stage
                    not in {
                        "draft",
                        "rewrite",
                    }
                    or not step.success
                    or not step.content.strip()
                ):

                    continue

                source_stage = (
                    "checkpoint"
                    if step.agent
                    == "checkpoint"
                    else step.stage
                )

                self._insert_version(
                    conn,
                    run_id=run_id,
                    version_index=(
                        version_index
                    ),
                    source_stage=(
                        source_stage
                    ),
                    round_index=(
                        step.round_index
                    ),
                    content=step.content,
                )

                version_index += 1

            self._insert_event(
                conn,
                run_id=run_id,
                sequence_no=sequence_no,
                event_type=(
                    "run_completed"
                    if execution_status
                    == "succeeded"
                    else "run_stopped"
                ),
                payload={
                    "execution_status": (
                        execution_status
                    ),
                    "workflow_status": (
                        result.status
                    ),
                    "quality_gate_passed": (
                        result
                        .quality_gate_passed
                    ),
                    "resumable": resumable,
                    "revision_rounds": (
                        result
                        .revision_rounds
                    ),
                },
            )

            conn.execute(
                """
                UPDATE workflow_runs
                SET
                    execution_status = ?,
                    workflow_status = ?,
                    quality_gate_passed = ?,
                    resumable = ?,
                    revision_rounds = ?,
                    result_json = ?,
                    latest_content = ?,
                    error = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE run_id = ?
                """,
                (
                    execution_status,
                    result.status,
                    int(
                        result
                        .quality_gate_passed
                    ),
                    int(
                        resumable
                    ),
                    result.revision_rounds,
                    _json_dumps(
                        result_payload
                    ),
                    result.final_content,
                    now,
                    now,
                    run_id,
                ),
            )

            conn.commit()

        return self.get_run(
            run_id
        )

    def fail_run(
        self,
        run_id: str,
        error: str,
    ) -> dict[str, Any]:

        now = _utc_now()

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT COALESCE(
                    MAX(sequence_no),
                    0
                ) AS max_sequence
                FROM workflow_run_events
                WHERE run_id = ?
                """,
                (
                    run_id,
                ),
            ).fetchone()

            next_sequence = (
                int(
                    row["max_sequence"]
                )
                + 1
            )

            self._insert_event(
                conn,
                run_id=run_id,
                sequence_no=(
                    next_sequence
                ),
                event_type="run_failed",
                payload={
                    "error": error
                },
            )

            conn.execute(
                """
                UPDATE workflow_runs
                SET
                    execution_status =
                        'failed',
                    resumable = 0,
                    error = ?,
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

            conn.commit()

        return self.get_run(
            run_id
        )

    def get_run(
        self,
        run_id: str,
    ) -> dict[str, Any]:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
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

            result = (
                self
                ._run_row_to_dict(
                    row
                )
            )

            event_rows = conn.execute(
                """
                SELECT *
                FROM workflow_run_events
                WHERE run_id = ?
                ORDER BY sequence_no ASC
                """,
                (
                    run_id,
                ),
            ).fetchall()

            version_rows = conn.execute(
                """
                SELECT *
                FROM
                workflow_chapter_versions
                WHERE run_id = ?
                ORDER BY version_index ASC
                """,
                (
                    run_id,
                ),
            ).fetchall()

        result["events"] = [
            {
                "event_id": (
                    event["event_id"]
                ),
                "run_id": event["run_id"],
                "sequence_no": int(
                    event["sequence_no"]
                ),
                "event_type": (
                    event["event_type"]
                ),
                "stage": event["stage"],
                "round_index": (
                    event["round_index"]
                ),
                "attempt_index": (
                    event[
                        "attempt_index"
                    ]
                ),
                "payload": json.loads(
                    event["payload_json"]
                ),
                "created_at": (
                    event["created_at"]
                ),
            }
            for event in event_rows
        ]

        result["versions"] = [
            {
                "version_id": (
                    version[
                        "version_id"
                    ]
                ),
                "run_id": version["run_id"],
                "version_index": int(
                    version[
                        "version_index"
                    ]
                ),
                "source_stage": (
                    version[
                        "source_stage"
                    ]
                ),
                "round_index": int(
                    version[
                        "round_index"
                    ]
                ),
                "content": (
                    version["content"]
                ),
                "content_hash": (
                    version[
                        "content_hash"
                    ]
                ),
                "created_at": (
                    version[
                        "created_at"
                    ]
                ),
            }
            for version in version_rows
        ]

        return result

    def list_runs(
        self,
        *,
        user_id: str | None = None,
        novel_id: str | None = None,
        root_run_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:

        clauses: list[str] = []
        parameters: list[Any] = []

        if user_id is not None:

            clauses.append(
                "user_id = ?"
            )

            parameters.append(
                user_id
            )

        if novel_id is not None:

            clauses.append(
                "novel_id = ?"
            )

            parameters.append(
                novel_id
            )

        if root_run_id is not None:

            clauses.append(
                "root_run_id = ?"
            )

            parameters.append(
                root_run_id
            )

        where_clause = (
            " WHERE "
            + " AND ".join(
                clauses
            )
            if clauses
            else ""
        )

        parameters.append(
            min(
                max(
                    int(limit),
                    1,
                ),
                200,
            )
        )

        query = (
            "SELECT * "
            "FROM workflow_runs"
            + where_clause
            + " ORDER BY created_at DESC "
            "LIMIT ?"
        )

        with self._connect() as conn:

            rows = conn.execute(
                query,
                tuple(
                    parameters
                ),
            ).fetchall()

        results = []

        for row in rows:

            value = (
                self
                ._run_row_to_dict(
                    row
                )
            )

            value.pop(
                "request",
                None,
            )

            value.pop(
                "result",
                None,
            )

            value.pop(
                "latest_content",
                None,
            )

            results.append(
                value
            )

        return results
