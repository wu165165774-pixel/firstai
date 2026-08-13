from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import uuid

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.consistency.schemas import ConsistencyFactCandidate
from app.fact_projection.schemas import (
    FactProjectionItem,
    FactProjectionSummary,
)

from .schemas import (
    ManuscriptAcceptResult,
    ManuscriptChapter,
    ManuscriptChapterDetail,
    ManuscriptImportResult,
    ManuscriptRevision,
)


class ManuscriptNotFoundError(LookupError):
    pass


class ManuscriptConflictError(RuntimeError):
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


class ManuscriptStorage:
    """Authoritative manuscript storage in the Novel domain database."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv(
            "NOVELFORGE_NOVEL_DB_PATH",
            "/app/data/novels.db",
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
                CREATE TABLE IF NOT EXISTS manuscript_chapters (
                    manuscript_chapter_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    chapter_plan_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    latest_revision INTEGER NOT NULL DEFAULT 0,
                    accepted_revision INTEGER,
                    accepted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(chapter_plan_id)
                        REFERENCES chapter_plans(chapter_plan_id)
                        ON DELETE RESTRICT,
                    UNIQUE(novel_id, chapter_number)
                );

                CREATE INDEX IF NOT EXISTS idx_manuscript_chapters_order
                ON manuscript_chapters(novel_id, chapter_number);

                CREATE TABLE IF NOT EXISTS manuscript_revisions (
                    manuscript_chapter_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_workflow_run_id TEXT NOT NULL,
                    source_workflow_version_id TEXT NOT NULL,
                    source_stage TEXT NOT NULL,
                    source_round_index INTEGER NOT NULL,
                    review_status TEXT NOT NULL,
                    quality_scores_json TEXT NOT NULL DEFAULT '{}',
                    review_summary TEXT NOT NULL DEFAULT '',
                    source_project_revision INTEGER NOT NULL,
                    source_story_bible_revision INTEGER NOT NULL,
                    source_novel_plan_revision INTEGER NOT NULL,
                    source_story_arc_id TEXT NOT NULL,
                    source_story_arc_revision INTEGER NOT NULL,
                    source_chapter_plan_id TEXT NOT NULL,
                    source_chapter_plan_revision INTEGER NOT NULL,
                    candidate_facts_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(manuscript_chapter_id, revision),
                    FOREIGN KEY(manuscript_chapter_id)
                        REFERENCES manuscript_chapters(manuscript_chapter_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE,
                    UNIQUE(source_workflow_run_id, source_workflow_version_id)
                );

                CREATE INDEX IF NOT EXISTS idx_manuscript_revisions_time
                ON manuscript_revisions(
                    manuscript_chapter_id,
                    revision DESC
                );

                CREATE INDEX IF NOT EXISTS idx_manuscript_revisions_run
                ON manuscript_revisions(source_workflow_run_id, revision);

                CREATE TABLE IF NOT EXISTS manuscript_fact_projections (
                    projection_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    manuscript_chapter_id TEXT NOT NULL,
                    manuscript_revision INTEGER NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    fact_index INTEGER NOT NULL,
                    fact_id TEXT NOT NULL,
                    fact_json TEXT NOT NULL,
                    operation TEXT NOT NULL DEFAULT 'project',
                    superseded_by_revision INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    memory_id TEXT,
                    memory_projected INTEGER NOT NULL DEFAULT 0,
                    vector_projected INTEGER NOT NULL DEFAULT 0,
                    graph_kind TEXT,
                    graph_id TEXT,
                    graph_projected INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(manuscript_chapter_id, manuscript_revision)
                        REFERENCES manuscript_revisions(
                            manuscript_chapter_id, revision
                        ) ON DELETE CASCADE,
                    UNIQUE(
                        manuscript_chapter_id,
                        manuscript_revision,
                        fact_index
                    ),
                    CHECK (operation IN ('project', 'retract')),
                    CHECK (
                        status IN (
                            'pending', 'processing', 'completed', 'failed'
                        )
                    ),
                    CHECK (
                        graph_kind IS NULL
                        OR graph_kind IN ('event', 'relation')
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_fact_projections_status
                ON manuscript_fact_projections(status, updated_at);

                CREATE INDEX IF NOT EXISTS idx_fact_projections_revision
                ON manuscript_fact_projections(
                    novel_id, manuscript_chapter_id,
                    manuscript_revision, fact_index
                );

                """
            )
            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(manuscript_revisions)"
                ).fetchall()
            }
            if "candidate_facts_json" not in columns:
                conn.execute(
                    "ALTER TABLE manuscript_revisions "
                    "ADD COLUMN candidate_facts_json TEXT "
                    "NOT NULL DEFAULT '[]'"
                )
            projection_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(manuscript_fact_projections)"
                ).fetchall()
            }
            if "operation" not in projection_columns:
                conn.execute(
                    "ALTER TABLE manuscript_fact_projections "
                    "ADD COLUMN operation TEXT NOT NULL DEFAULT 'project'"
                )
            if "superseded_by_revision" not in projection_columns:
                conn.execute(
                    "ALTER TABLE manuscript_fact_projections "
                    "ADD COLUMN superseded_by_revision INTEGER"
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fact_projections_replacement
                ON manuscript_fact_projections(
                    manuscript_chapter_id,
                    superseded_by_revision,
                    operation,
                    status
                )
                """
            )
            conn.commit()

    @staticmethod
    def _chapter_from_row(row: sqlite3.Row) -> ManuscriptChapter:
        return ManuscriptChapter(
            manuscript_chapter_id=row["manuscript_chapter_id"],
            novel_id=row["novel_id"],
            chapter_number=int(row["chapter_number"]),
            chapter_plan_id=row["chapter_plan_id"],
            revision=int(row["revision"]),
            latest_revision=int(row["latest_revision"]),
            accepted_revision=(
                int(row["accepted_revision"])
                if row["accepted_revision"] is not None
                else None
            ),
            accepted_at=row["accepted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _revision_from_row(
        row: sqlite3.Row,
        *,
        accepted_revision: int | None,
    ) -> ManuscriptRevision:
        revision = int(row["revision"])
        return ManuscriptRevision(
            manuscript_chapter_id=row["manuscript_chapter_id"],
            novel_id=row["novel_id"],
            revision=revision,
            content=row["content"],
            content_hash=row["content_hash"],
            source_workflow_run_id=row["source_workflow_run_id"],
            source_workflow_version_id=(
                row["source_workflow_version_id"]
            ),
            source_stage=row["source_stage"],
            source_round_index=int(row["source_round_index"]),
            review_status=row["review_status"],
            quality_scores=_json_load(
                row["quality_scores_json"],
                {},
            ),
            review_summary=row["review_summary"],
            source_project_revision=int(
                row["source_project_revision"]
            ),
            source_story_bible_revision=int(
                row["source_story_bible_revision"]
            ),
            source_novel_plan_revision=int(
                row["source_novel_plan_revision"]
            ),
            source_story_arc_id=row["source_story_arc_id"],
            source_story_arc_revision=int(
                row["source_story_arc_revision"]
            ),
            source_chapter_plan_id=row["source_chapter_plan_id"],
            source_chapter_plan_revision=int(
                row["source_chapter_plan_revision"]
            ),
            candidate_facts=[
                ConsistencyFactCandidate.model_validate(item)
                for item in _json_load(
                    row["candidate_facts_json"]
                    if "candidate_facts_json" in row.keys()
                    else None,
                    [],
                )
            ],
            is_accepted=(accepted_revision == revision),
            created_at=row["created_at"],
        )

    @staticmethod
    def _projection_from_row(row: sqlite3.Row) -> FactProjectionItem:
        return FactProjectionItem(
            projection_id=row["projection_id"],
            novel_id=row["novel_id"],
            manuscript_chapter_id=row["manuscript_chapter_id"],
            manuscript_revision=int(row["manuscript_revision"]),
            chapter_number=int(row["chapter_number"]),
            fact_index=int(row["fact_index"]),
            fact_id=row["fact_id"],
            operation=(
                row["operation"]
                if "operation" in row.keys()
                else "project"
            ),
            superseded_by_revision=(
                int(row["superseded_by_revision"])
                if "superseded_by_revision" in row.keys()
                and row["superseded_by_revision"] is not None
                else None
            ),
            status=row["status"],
            attempts=int(row["attempts"]),
            memory_id=row["memory_id"],
            memory_projected=bool(row["memory_projected"]),
            vector_projected=bool(row["vector_projected"]),
            graph_kind=row["graph_kind"],
            graph_id=row["graph_id"],
            graph_projected=bool(row["graph_projected"]),
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @classmethod
    def _projection_rows(
        cls,
        conn: sqlite3.Connection,
        novel_id: str,
        manuscript_chapter_id: str,
        manuscript_revision: int,
    ) -> list[sqlite3.Row]:
        return list(
            conn.execute(
                """
                SELECT * FROM manuscript_fact_projections
                WHERE novel_id = ? AND manuscript_chapter_id = ?
                  AND (
                      manuscript_revision = ?
                      OR superseded_by_revision = ?
                  )
                ORDER BY CASE operation WHEN 'retract' THEN 0 ELSE 1 END,
                         manuscript_revision ASC, fact_index ASC
                """,
                (
                    novel_id,
                    manuscript_chapter_id,
                    manuscript_revision,
                    manuscript_revision,
                ),
            ).fetchall()
        )

    @classmethod
    def _projection_summary_from_rows(
        cls,
        novel_id: str,
        manuscript_chapter_id: str,
        manuscript_revision: int,
        rows: list[sqlite3.Row],
    ) -> FactProjectionSummary:
        items = [cls._projection_from_row(row) for row in rows]
        counts = {
            status: sum(item.status == status for item in items)
            for status in ("pending", "processing", "completed", "failed")
        }
        if not items:
            overall = "completed"
        elif counts["failed"]:
            overall = "failed"
        elif counts["processing"]:
            overall = "processing"
        elif counts["pending"]:
            overall = "pending"
        else:
            overall = "completed"
        return FactProjectionSummary(
            novel_id=novel_id,
            manuscript_chapter_id=manuscript_chapter_id,
            manuscript_revision=manuscript_revision,
            status=overall,
            total_count=len(items),
            pending_count=counts["pending"],
            processing_count=counts["processing"],
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            items=items,
        )

    @staticmethod
    def _projection_id(
        manuscript_chapter_id: str,
        manuscript_revision: int,
        fact_index: int,
        fact: ConsistencyFactCandidate,
    ) -> str:
        digest = hashlib.sha256(
            (
                f"{manuscript_chapter_id}|{manuscript_revision}|"
                f"{fact_index}|"
                + _json_dump(fact.model_dump(mode="json"))
            ).encode("utf-8")
        ).hexdigest()[:32]
        return f"fp_{digest}"

    def _enqueue_fact_projections(
        self,
        conn: sqlite3.Connection,
        chapter_row: sqlite3.Row,
        revision_row: sqlite3.Row,
        now: str,
    ) -> None:
        facts = [
            ConsistencyFactCandidate.model_validate(item)
            for item in _json_load(
                revision_row["candidate_facts_json"],
                [],
            )
        ]
        for fact_index, fact in enumerate(facts):
            projection_id = self._projection_id(
                revision_row["manuscript_chapter_id"],
                int(revision_row["revision"]),
                fact_index,
                fact,
            )
            existing = conn.execute(
                """
                SELECT projection_id FROM manuscript_fact_projections
                WHERE manuscript_chapter_id = ?
                  AND manuscript_revision = ?
                  AND fact_index = ?
                """,
                (
                    revision_row["manuscript_chapter_id"],
                    int(revision_row["revision"]),
                    fact_index,
                ),
            ).fetchone()
            if (
                existing is not None
                and existing["projection_id"] != projection_id
            ):
                raise ManuscriptConflictError(
                    "Accepted fact outbox identity does not match its frozen "
                    "Manuscript revision."
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO manuscript_fact_projections (
                    projection_id, novel_id, manuscript_chapter_id,
                    manuscript_revision, chapter_number, fact_index,
                    fact_id, fact_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    projection_id,
                    revision_row["novel_id"],
                    revision_row["manuscript_chapter_id"],
                    int(revision_row["revision"]),
                    int(chapter_row["chapter_number"]),
                    fact_index,
                    fact.fact_id or f"FACT-{fact_index + 1:03d}",
                    _json_dump(fact.model_dump(mode="json")),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE manuscript_fact_projections
                SET operation = 'project', superseded_by_revision = NULL,
                    status = 'pending', completed_at = NULL,
                    last_error = '', memory_projected = 0,
                    vector_projected = 0, graph_projected = 0,
                    updated_at = ?
                WHERE projection_id = ? AND operation = 'retract'
                """,
                (now, projection_id),
            )

    def _enqueue_fact_retractions(
        self,
        conn: sqlite3.Connection,
        chapter_row: sqlite3.Row,
        manuscript_revision: int,
        superseded_by_revision: int,
        now: str,
    ) -> None:
        revision_row = conn.execute(
            """
            SELECT * FROM manuscript_revisions
            WHERE manuscript_chapter_id = ? AND revision = ?
            """,
            (chapter_row["manuscript_chapter_id"], manuscript_revision),
        ).fetchone()
        if revision_row is None:
            return
        self._enqueue_fact_projections(conn, chapter_row, revision_row, now)
        conn.execute(
            """
            UPDATE manuscript_fact_projections
            SET operation = 'retract', superseded_by_revision = ?,
                status = 'pending', completed_at = NULL,
                last_error = '', memory_projected = 0,
                vector_projected = 0, graph_projected = 0,
                updated_at = ?
            WHERE manuscript_chapter_id = ?
              AND manuscript_revision = ?
            """,
            (
                superseded_by_revision,
                now,
                chapter_row["manuscript_chapter_id"],
                manuscript_revision,
            ),
        )
        conn.execute(
            """
            UPDATE manuscript_fact_projections
            SET superseded_by_revision = ?, status = 'pending',
                completed_at = NULL, last_error = '',
                graph_projected = 0, updated_at = ?
            WHERE manuscript_chapter_id = ?
              AND operation = 'retract'
              AND status != 'completed'
            """,
            (
                superseded_by_revision,
                now,
                chapter_row["manuscript_chapter_id"],
            ),
        )

    def get_fact_projection(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        manuscript_revision: int,
    ) -> FactProjectionSummary:
        with self._connect() as conn:
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            revision_row = conn.execute(
                """
                SELECT 1 FROM manuscript_revisions
                WHERE novel_id = ? AND manuscript_chapter_id = ?
                  AND revision = ?
                """,
                (novel_id, manuscript_chapter_id, manuscript_revision),
            ).fetchone()
            if revision_row is None:
                raise ManuscriptNotFoundError(
                    "Manuscript Revision not found: "
                    f"{manuscript_chapter_id}:{manuscript_revision}"
                )
            rows = self._projection_rows(
                conn,
                novel_id,
                manuscript_chapter_id,
                manuscript_revision,
            )
        return self._projection_summary_from_rows(
            novel_id,
            manuscript_chapter_id,
            manuscript_revision,
            list(rows),
        )

    def get_projection_status(
        self,
        projection_id: str,
    ) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status FROM manuscript_fact_projections
                WHERE projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
        if row is None:
            raise ManuscriptNotFoundError(
                f"Fact Projection not found: {projection_id}"
            )
        return str(row["status"])

    def peek_fact_projection(
        self,
        projection_id: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM manuscript_fact_projections
                WHERE projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
        if row is None:
            raise ManuscriptNotFoundError(
                f"Fact Projection not found: {projection_id}"
            )
        return dict(row)

    def list_incomplete_fact_projection_ids(
        self,
        *,
        manuscript_chapter_id: str | None = None,
        limit: int | None = None,
    ) -> list[str]:
        clauses = ["status IN ('pending', 'failed')"]
        params: list[Any] = []
        if manuscript_chapter_id is not None:
            clauses.append("manuscript_chapter_id = ?")
            params.append(manuscript_chapter_id)
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT projection_id FROM manuscript_fact_projections
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE operation WHEN 'retract' THEN 0 ELSE 1 END,
                         created_at ASC, fact_index ASC
                {limit_sql}
                """,
                tuple(params),
            ).fetchall()
        return [str(row["projection_id"]) for row in rows]

    def has_incomplete_fact_projections(
        self,
        manuscript_chapter_id: str,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM manuscript_fact_projections
                WHERE manuscript_chapter_id = ?
                  AND status IN ('pending', 'failed')
                LIMIT 1
                """,
                (manuscript_chapter_id,),
            ).fetchone()
        return row is not None

    def recover_processing_fact_projections(self) -> int:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE manuscript_fact_projections
                SET status = 'failed',
                    last_error = 'Projection interrupted before completion.',
                    updated_at = ?
                WHERE status = 'processing'
                """,
                (now,),
            )
            conn.commit()
        return int(cursor.rowcount)

    def claim_fact_projection(
        self,
        projection_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM manuscript_fact_projections
                WHERE projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
            if row is None:
                raise ManuscriptNotFoundError(
                    f"Fact Projection not found: {projection_id}"
                )
            if row["status"] in {"completed", "processing"}:
                conn.commit()
                return None
            if row["operation"] == "project":
                current_chapter = conn.execute(
                    """
                    SELECT accepted_revision FROM manuscript_chapters
                    WHERE manuscript_chapter_id = ?
                    """,
                    (row["manuscript_chapter_id"],),
                ).fetchone()
                if (
                    current_chapter is None
                    or current_chapter["accepted_revision"] is None
                    or int(current_chapter["accepted_revision"])
                    != int(row["manuscript_revision"])
                ):
                    conn.execute(
                        """
                        UPDATE manuscript_fact_projections
                        SET status = 'failed',
                            last_error = ?, updated_at = ?
                        WHERE projection_id = ?
                        """,
                        (
                            "Projection source Manuscript revision is no "
                            "longer accepted.",
                            _utc_now(),
                            projection_id,
                        ),
                    )
                    conn.commit()
                    return None
                blocking_retraction = conn.execute(
                    """
                    SELECT 1 FROM manuscript_fact_projections
                    WHERE manuscript_chapter_id = ?
                      AND operation = 'retract'
                      AND superseded_by_revision = ?
                      AND status != 'completed'
                    LIMIT 1
                    """,
                    (
                        row["manuscript_chapter_id"],
                        row["manuscript_revision"],
                    ),
                ).fetchone()
                if blocking_retraction is not None:
                    conn.commit()
                    return None
            else:
                current_chapter = conn.execute(
                    """
                    SELECT accepted_revision FROM manuscript_chapters
                    WHERE manuscript_chapter_id = ?
                    """,
                    (row["manuscript_chapter_id"],),
                ).fetchone()
                if (
                    current_chapter is None
                    or row["superseded_by_revision"] is None
                    or current_chapter["accepted_revision"] is None
                    or int(current_chapter["accepted_revision"])
                    != int(row["superseded_by_revision"])
                ):
                    conn.execute(
                        """
                        UPDATE manuscript_fact_projections
                        SET status = 'failed',
                            last_error = ?, updated_at = ?
                        WHERE projection_id = ?
                        """,
                        (
                            "Fact retraction replacement Manuscript revision "
                            "is no longer accepted.",
                            _utc_now(),
                            projection_id,
                        ),
                    )
                    conn.commit()
                    return None
            now = _utc_now()
            conn.execute(
                """
                UPDATE manuscript_fact_projections
                SET status = 'processing', attempts = attempts + 1,
                    last_error = '', updated_at = ?
                WHERE projection_id = ?
                """,
                (now, projection_id),
            )
            updated = conn.execute(
                """
                SELECT p.*, r.content
                FROM manuscript_fact_projections AS p
                JOIN manuscript_revisions AS r
                  ON r.manuscript_chapter_id = p.manuscript_chapter_id
                 AND r.revision = p.manuscript_revision
                WHERE p.projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
            conn.commit()
        value = dict(updated)
        value["fact"] = ConsistencyFactCandidate.model_validate(
            _json_load(value.pop("fact_json"), {})
        )
        return value

    def update_fact_projection(
        self,
        projection_id: str,
        *,
        memory_id: str | None = None,
        memory_projected: bool | None = None,
        vector_projected: bool | None = None,
        graph_kind: str | None = None,
        graph_id: str | None = None,
        graph_projected: bool | None = None,
        completed: bool = False,
        error: str | None = None,
        expected_operation: str | None = None,
    ) -> None:
        assignments = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]
        for column, value in (
            ("memory_id", memory_id),
            ("memory_projected", memory_projected),
            ("vector_projected", vector_projected),
            ("graph_kind", graph_kind),
            ("graph_id", graph_id),
            ("graph_projected", graph_projected),
        ):
            if value is None:
                continue
            assignments.append(f"{column} = ?")
            values.append(int(value) if isinstance(value, bool) else value)
        if completed:
            assignments.extend(
                ["status = 'completed'", "completed_at = ?", "last_error = ''"]
            )
            values.append(_utc_now())
        elif error is not None:
            assignments.extend(["status = 'failed'", "last_error = ?"])
            values.append(str(error)[:8000])
        values.append(projection_id)
        where = "projection_id = ?"
        if expected_operation is not None:
            where += " AND operation = ?"
            values.append(expected_operation)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE manuscript_fact_projections
                SET {', '.join(assignments)}
                WHERE {where}
                """,
                tuple(values),
            )
            if cursor.rowcount != 1:
                raise ManuscriptConflictError(
                    "Fact Projection operation changed while processing: "
                    f"{projection_id}"
                )
            conn.commit()

    @staticmethod
    def _planning_row(
        conn: sqlite3.Connection,
        novel_id: str,
        chapter_plan_id: str,
    ) -> sqlite3.Row:
        project = conn.execute(
            "SELECT novel_id FROM novel_projects WHERE novel_id = ?",
            (novel_id,),
        ).fetchone()
        if project is None:
            raise ManuscriptNotFoundError(
                f"Novel Project not found: {novel_id}"
            )

        row = conn.execute(
            """
            SELECT
                p.revision AS project_revision,
                b.revision AS story_bible_revision,
                np.revision AS novel_plan_revision,
                np.source_project_revision AS plan_project_revision,
                np.source_story_bible_revision AS plan_bible_revision,
                a.arc_id AS story_arc_id,
                a.revision AS story_arc_revision,
                a.source_project_revision AS arc_project_revision,
                a.source_story_bible_revision AS arc_bible_revision,
                a.source_novel_plan_revision AS arc_plan_revision,
                cp.chapter_number AS chapter_number,
                cp.revision AS chapter_plan_revision,
                cp.source_project_revision AS chapter_project_revision,
                cp.source_story_bible_revision AS chapter_bible_revision,
                cp.source_novel_plan_revision AS chapter_plan_source_revision,
                cp.source_story_arc_revision AS chapter_arc_revision
            FROM chapter_plans AS cp
            JOIN novel_projects AS p ON p.novel_id = cp.novel_id
            JOIN story_bibles AS b ON b.novel_id = cp.novel_id
            JOIN novel_plans AS np ON np.novel_id = cp.novel_id
            JOIN story_arcs AS a ON a.arc_id = cp.arc_id
            WHERE cp.novel_id = ? AND cp.chapter_plan_id = ?
            """,
            (novel_id, chapter_plan_id),
        ).fetchone()
        if row is None:
            raise ManuscriptNotFoundError(
                f"Chapter Plan not found: {novel_id}:{chapter_plan_id}"
            )
        return row

    @classmethod
    def _assert_fresh_sources(
        cls,
        conn: sqlite3.Connection,
        novel_id: str,
        chapter_plan_id: str,
        expected: dict[str, Any],
    ) -> sqlite3.Row:
        row = cls._planning_row(conn, novel_id, chapter_plan_id)

        if (
            int(row["plan_project_revision"])
            != int(row["project_revision"])
            or int(row["plan_bible_revision"])
            != int(row["story_bible_revision"])
        ):
            raise ManuscriptConflictError(
                "Novel Plan is stale; refresh it before importing or "
                "accepting manuscript content."
            )
        if (
            int(row["arc_project_revision"])
            != int(row["project_revision"])
            or int(row["arc_bible_revision"])
            != int(row["story_bible_revision"])
            or int(row["arc_plan_revision"])
            != int(row["novel_plan_revision"])
        ):
            raise ManuscriptConflictError(
                "Selected Story Arc is stale; refresh it before "
                "importing or accepting manuscript content."
            )
        if (
            int(row["chapter_project_revision"])
            != int(row["project_revision"])
            or int(row["chapter_bible_revision"])
            != int(row["story_bible_revision"])
            or int(row["chapter_plan_source_revision"])
            != int(row["novel_plan_revision"])
            or int(row["chapter_arc_revision"])
            != int(row["story_arc_revision"])
        ):
            raise ManuscriptConflictError(
                "Selected Chapter Plan is stale; refresh it before "
                "importing or accepting manuscript content."
            )

        comparisons = {
            "source_project_revision": "project_revision",
            "source_story_bible_revision": "story_bible_revision",
            "source_novel_plan_revision": "novel_plan_revision",
            "source_story_arc_revision": "story_arc_revision",
            "source_chapter_plan_revision": "chapter_plan_revision",
        }
        for source_name, column in comparisons.items():
            wanted = int(expected[source_name])
            current = int(row[column])
            if wanted != current:
                raise ManuscriptConflictError(
                    "Manuscript source revision conflict: "
                    f"source={source_name}, expected={wanted}, "
                    f"current={current}."
                )
        if expected["source_story_arc_id"] != row["story_arc_id"]:
            raise ManuscriptConflictError(
                "Manuscript source Story Arc conflict: "
                f"expected={expected['source_story_arc_id']}, "
                f"current={row['story_arc_id']}."
            )
        return row

    @staticmethod
    def _chapter_row(
        conn: sqlite3.Connection,
        novel_id: str,
        manuscript_chapter_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT * FROM manuscript_chapters
            WHERE novel_id = ? AND manuscript_chapter_id = ?
            """,
            (novel_id, manuscript_chapter_id),
        ).fetchone()
        if row is None:
            raise ManuscriptNotFoundError(
                "Manuscript Chapter not found: "
                f"{novel_id}:{manuscript_chapter_id}"
            )
        return row

    def import_workflow_candidate(
        self,
        candidate: dict[str, Any],
        *,
        expected_manuscript_revision: int | None,
    ) -> ManuscriptImportResult:
        novel_id = candidate["novel_id"]
        run_id = candidate["workflow_run_id"]

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            duplicate_rows = conn.execute(
                """
                SELECT r.*, c.accepted_revision
                FROM manuscript_revisions AS r
                JOIN manuscript_chapters AS c
                  ON c.manuscript_chapter_id = r.manuscript_chapter_id
                WHERE r.source_workflow_run_id = ?
                ORDER BY r.revision ASC
                """,
                (run_id,),
            ).fetchall()
            if duplicate_rows:
                if duplicate_rows[0]["novel_id"] != novel_id:
                    raise ManuscriptConflictError(
                        "Workflow Run is already imported by another novel."
                    )
                chapter_row = self._chapter_row(
                    conn,
                    novel_id,
                    duplicate_rows[0]["manuscript_chapter_id"],
                )
                conn.commit()
                return ManuscriptImportResult(
                    chapter=self._chapter_from_row(chapter_row),
                    imported_revisions=[
                        self._revision_from_row(
                            row,
                            accepted_revision=chapter_row[
                                "accepted_revision"
                            ],
                        )
                        for row in duplicate_rows
                    ],
                    deduplicated=True,
                )

            planning = self._assert_fresh_sources(
                conn,
                novel_id,
                candidate["chapter_plan_id"],
                candidate,
            )
            chapter_number = int(planning["chapter_number"])
            chapter_row = conn.execute(
                """
                SELECT * FROM manuscript_chapters
                WHERE novel_id = ? AND chapter_number = ?
                """,
                (novel_id, chapter_number),
            ).fetchone()
            now = _utc_now()

            if chapter_row is None:
                if expected_manuscript_revision is not None:
                    raise ManuscriptConflictError(
                        "Manuscript Chapter does not exist; "
                        "expected_manuscript_revision must be omitted."
                    )
                manuscript_chapter_id = str(uuid.uuid4())
                aggregate_revision = 1
                latest_revision = 0
                conn.execute(
                    """
                    INSERT INTO manuscript_chapters (
                        manuscript_chapter_id,
                        novel_id,
                        chapter_number,
                        chapter_plan_id,
                        revision,
                        latest_revision,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, 1, 0, ?, ?)
                    """,
                    (
                        manuscript_chapter_id,
                        novel_id,
                        chapter_number,
                        candidate["chapter_plan_id"],
                        now,
                        now,
                    ),
                )
            else:
                manuscript_chapter_id = chapter_row[
                    "manuscript_chapter_id"
                ]
                if chapter_row["chapter_plan_id"] != candidate[
                    "chapter_plan_id"
                ]:
                    raise ManuscriptConflictError(
                        "Manuscript Chapter is bound to a different "
                        "Chapter Plan."
                    )
                if expected_manuscript_revision is None:
                    raise ManuscriptConflictError(
                        "expected_manuscript_revision is required when "
                        "appending to an existing Manuscript Chapter."
                    )
                current_revision = int(chapter_row["revision"])
                if expected_manuscript_revision != current_revision:
                    raise ManuscriptConflictError(
                        "Manuscript Chapter revision conflict: "
                        f"expected={expected_manuscript_revision}, "
                        f"current={current_revision}."
                    )
                aggregate_revision = current_revision + 1
                latest_revision = int(chapter_row["latest_revision"])

            imported: list[ManuscriptRevision] = []
            accepted_revision = (
                int(chapter_row["accepted_revision"])
                if chapter_row is not None
                and chapter_row["accepted_revision"] is not None
                else None
            )
            for offset, version in enumerate(candidate["versions"], 1):
                revision = latest_revision + offset
                conn.execute(
                    """
                    INSERT INTO manuscript_revisions (
                        manuscript_chapter_id,
                        novel_id,
                        revision,
                        content,
                        content_hash,
                        source_workflow_run_id,
                        source_workflow_version_id,
                        source_stage,
                        source_round_index,
                        review_status,
                        quality_scores_json,
                        review_summary,
                        source_project_revision,
                        source_story_bible_revision,
                        source_novel_plan_revision,
                        source_story_arc_id,
                        source_story_arc_revision,
                        source_chapter_plan_id,
                        source_chapter_plan_revision,
                        candidate_facts_json,
                        created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        manuscript_chapter_id,
                        novel_id,
                        revision,
                        version["content"],
                        version["content_hash"],
                        run_id,
                        version["version_id"],
                        version["source_stage"],
                        int(version["round_index"]),
                        version["review_status"],
                        _json_dump(version["quality_scores"]),
                        version["review_summary"],
                        int(candidate["source_project_revision"]),
                        int(candidate["source_story_bible_revision"]),
                        int(candidate["source_novel_plan_revision"]),
                        candidate["source_story_arc_id"],
                        int(candidate["source_story_arc_revision"]),
                        candidate["chapter_plan_id"],
                        int(candidate["source_chapter_plan_revision"]),
                        _json_dump(version["candidate_facts"]),
                        now,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT * FROM manuscript_revisions
                    WHERE manuscript_chapter_id = ? AND revision = ?
                    """,
                    (manuscript_chapter_id, revision),
                ).fetchone()
                imported.append(
                    self._revision_from_row(
                        row,
                        accepted_revision=accepted_revision,
                    )
                )

            new_latest = latest_revision + len(candidate["versions"])
            conn.execute(
                """
                UPDATE manuscript_chapters
                SET revision = ?, latest_revision = ?, updated_at = ?
                WHERE manuscript_chapter_id = ?
                """,
                (
                    aggregate_revision,
                    new_latest,
                    now,
                    manuscript_chapter_id,
                ),
            )
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            conn.commit()

        return ManuscriptImportResult(
            chapter=self._chapter_from_row(chapter_row),
            imported_revisions=imported,
            deduplicated=False,
        )

    def accept_revision(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        revision: int,
        *,
        expected_manuscript_revision: int,
    ) -> ManuscriptAcceptResult:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            current_revision = int(chapter_row["revision"])
            if expected_manuscript_revision != current_revision:
                raise ManuscriptConflictError(
                    "Manuscript Chapter revision conflict: "
                    f"expected={expected_manuscript_revision}, "
                    f"current={current_revision}."
                )

            revision_row = conn.execute(
                """
                SELECT * FROM manuscript_revisions
                WHERE manuscript_chapter_id = ? AND revision = ?
                """,
                (manuscript_chapter_id, revision),
            ).fetchone()
            if revision_row is None:
                raise ManuscriptNotFoundError(
                    "Manuscript Revision not found: "
                    f"{manuscript_chapter_id}:{revision}"
                )
            if revision_row["review_status"] != "approved":
                raise ManuscriptConflictError(
                    "Only an approved reviewed candidate can be accepted."
                )

            if chapter_row["accepted_revision"] == revision:
                projection_rows = self._projection_rows(
                    conn,
                    novel_id,
                    manuscript_chapter_id,
                    revision,
                )
                conn.commit()
                return ManuscriptAcceptResult(
                    chapter=self._chapter_from_row(chapter_row),
                    accepted_revision=self._revision_from_row(
                        revision_row,
                        accepted_revision=revision,
                    ),
                    changed=False,
                    fact_projection=self._projection_summary_from_rows(
                        novel_id,
                        manuscript_chapter_id,
                        revision,
                        list(projection_rows),
                    ),
                )

            processing = conn.execute(
                """
                SELECT projection_id FROM manuscript_fact_projections
                WHERE manuscript_chapter_id = ? AND status = 'processing'
                LIMIT 1
                """,
                (manuscript_chapter_id,),
            ).fetchone()
            if processing is not None:
                raise ManuscriptConflictError(
                    "A fact projection is currently processing for this "
                    "Manuscript Chapter; retry acceptance after it finishes."
                )

            expected = {
                "source_project_revision": revision_row[
                    "source_project_revision"
                ],
                "source_story_bible_revision": revision_row[
                    "source_story_bible_revision"
                ],
                "source_novel_plan_revision": revision_row[
                    "source_novel_plan_revision"
                ],
                "source_story_arc_id": revision_row[
                    "source_story_arc_id"
                ],
                "source_story_arc_revision": revision_row[
                    "source_story_arc_revision"
                ],
                "source_chapter_plan_revision": revision_row[
                    "source_chapter_plan_revision"
                ],
            }
            self._assert_fresh_sources(
                conn,
                novel_id,
                revision_row["source_chapter_plan_id"],
                expected,
            )

            now = _utc_now()
            previous_accepted_revision = (
                int(chapter_row["accepted_revision"])
                if chapter_row["accepted_revision"] is not None
                else None
            )
            if (
                previous_accepted_revision is not None
                and previous_accepted_revision != revision
            ):
                self._enqueue_fact_retractions(
                    conn,
                    chapter_row,
                    previous_accepted_revision,
                    revision,
                    now,
                )
            conn.execute(
                """
                UPDATE manuscript_chapters
                SET
                    revision = revision + 1,
                    accepted_revision = ?,
                    accepted_at = ?,
                    updated_at = ?
                WHERE manuscript_chapter_id = ?
                """,
                (revision, now, now, manuscript_chapter_id),
            )
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            self._enqueue_fact_projections(
                conn,
                chapter_row,
                revision_row,
                now,
            )
            projection_rows = self._projection_rows(
                conn,
                novel_id,
                manuscript_chapter_id,
                revision,
            )
            conn.commit()

        return ManuscriptAcceptResult(
            chapter=self._chapter_from_row(chapter_row),
            accepted_revision=self._revision_from_row(
                revision_row,
                accepted_revision=revision,
            ),
            changed=True,
            fact_projection=self._projection_summary_from_rows(
                novel_id,
                manuscript_chapter_id,
                revision,
                list(projection_rows),
            ),
        )

    def list_chapters(
        self,
        novel_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ManuscriptChapter]:
        with self._connect() as conn:
            if conn.execute(
                "SELECT 1 FROM novel_projects WHERE novel_id = ?",
                (novel_id,),
            ).fetchone() is None:
                raise ManuscriptNotFoundError(
                    f"Novel Project not found: {novel_id}"
                )
            rows = conn.execute(
                """
                SELECT * FROM manuscript_chapters
                WHERE novel_id = ?
                ORDER BY chapter_number ASC
                LIMIT ? OFFSET ?
                """,
                (novel_id, limit, offset),
            ).fetchall()
        return [self._chapter_from_row(row) for row in rows]

    def get_chapter(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
    ) -> ManuscriptChapterDetail:
        with self._connect() as conn:
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            latest_row = conn.execute(
                """
                SELECT * FROM manuscript_revisions
                WHERE manuscript_chapter_id = ? AND revision = ?
                """,
                (
                    manuscript_chapter_id,
                    chapter_row["latest_revision"],
                ),
            ).fetchone()
            accepted_row = None
            if chapter_row["accepted_revision"] is not None:
                accepted_row = conn.execute(
                    """
                    SELECT * FROM manuscript_revisions
                    WHERE manuscript_chapter_id = ? AND revision = ?
                    """,
                    (
                        manuscript_chapter_id,
                        chapter_row["accepted_revision"],
                    ),
                ).fetchone()
        accepted_revision = chapter_row["accepted_revision"]
        return ManuscriptChapterDetail(
            chapter=self._chapter_from_row(chapter_row),
            latest=(
                self._revision_from_row(
                    latest_row,
                    accepted_revision=accepted_revision,
                )
                if latest_row is not None
                else None
            ),
            accepted=(
                self._revision_from_row(
                    accepted_row,
                    accepted_revision=accepted_revision,
                )
                if accepted_row is not None
                else None
            ),
        )

    def list_revisions(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        *,
        limit: int = 100,
    ) -> list[ManuscriptRevision]:
        with self._connect() as conn:
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            rows = conn.execute(
                """
                SELECT * FROM manuscript_revisions
                WHERE manuscript_chapter_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (manuscript_chapter_id, limit),
            ).fetchall()
        return [
            self._revision_from_row(
                row,
                accepted_revision=chapter_row["accepted_revision"],
            )
            for row in rows
        ]

    def get_revision(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        revision: int,
    ) -> ManuscriptRevision:
        with self._connect() as conn:
            chapter_row = self._chapter_row(
                conn,
                novel_id,
                manuscript_chapter_id,
            )
            row = conn.execute(
                """
                SELECT * FROM manuscript_revisions
                WHERE manuscript_chapter_id = ? AND revision = ?
                """,
                (manuscript_chapter_id, revision),
            ).fetchone()
        if row is None:
            raise ManuscriptNotFoundError(
                "Manuscript Revision not found: "
                f"{manuscript_chapter_id}:{revision}"
            )
        return self._revision_from_row(
            row,
            accepted_revision=chapter_row["accepted_revision"],
        )

    def list_accepted_before(
        self,
        novel_id: str,
        chapter_number: int,
        *,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.manuscript_chapter_id,
                    c.chapter_number,
                    c.accepted_revision,
                    r.content,
                    r.content_hash,
                    r.source_chapter_plan_id,
                    r.source_chapter_plan_revision
                FROM manuscript_chapters AS c
                JOIN manuscript_revisions AS r
                  ON r.manuscript_chapter_id = c.manuscript_chapter_id
                 AND r.revision = c.accepted_revision
                WHERE c.novel_id = ? AND c.chapter_number < ?
                ORDER BY c.chapter_number DESC
                LIMIT ?
                """,
                (novel_id, chapter_number, limit),
            ).fetchall()
        values = [dict(row) for row in rows]
        values.reverse()
        return values
