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
    TemporalEvent,
    TemporalEventCreate,
    TemporalEventRevision,
    TemporalEventUpdate,
    TemporalRelation,
    TemporalRelationCreate,
    TemporalRelationRevision,
    TemporalRelationUpdate,
    TemporalSourceReference,
)


class TemporalGraphNotFoundError(LookupError):
    pass


class TemporalGraphConflictError(RuntimeError):
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
    return json.loads(value) if value else default


class TemporalGraphStorage:
    """SQLite authority for temporal events, relationships, and revisions."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv(
            "NOVELFORGE_TEMPORAL_GRAPH_DB_PATH",
            "/app/data/temporal_graph.db",
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
                CREATE TABLE IF NOT EXISTS temporal_events (
                    event_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    context_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    location_entity_id TEXT,
                    start_chapter INTEGER NOT NULL,
                    end_chapter INTEGER,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    source_chapter_number INTEGER,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (end_chapter IS NULL OR end_chapter >= start_chapter)
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_events_scope
                ON temporal_events(
                    novel_id, start_chapter, end_chapter, event_type, event_id
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_events_source
                ON temporal_events(
                    novel_id, source_type, source_id, source_revision
                );

                CREATE TABLE IF NOT EXISTS temporal_event_participants (
                    event_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    participant_order INTEGER NOT NULL,
                    PRIMARY KEY(event_id, entity_id),
                    FOREIGN KEY(event_id) REFERENCES temporal_events(event_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_participants_entity
                ON temporal_event_participants(entity_id, event_id);

                CREATE TABLE IF NOT EXISTS temporal_event_revisions (
                    event_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, revision),
                    FOREIGN KEY(event_id) REFERENCES temporal_events(event_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS temporal_relations (
                    relation_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    subject_entity_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_entity_id TEXT NOT NULL,
                    context_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    valid_from_chapter INTEGER NOT NULL,
                    valid_to_chapter INTEGER,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    source_chapter_number INTEGER,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (
                        valid_to_chapter IS NULL
                        OR valid_to_chapter >= valid_from_chapter
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_relations_scope
                ON temporal_relations(
                    novel_id, valid_from_chapter, valid_to_chapter,
                    predicate, relation_id
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_relations_entities
                ON temporal_relations(
                    novel_id, subject_entity_id, object_entity_id
                );

                CREATE INDEX IF NOT EXISTS idx_temporal_relations_source
                ON temporal_relations(
                    novel_id, source_type, source_id, source_revision
                );

                CREATE TABLE IF NOT EXISTS temporal_relation_revisions (
                    relation_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(relation_id, revision),
                    FOREIGN KEY(relation_id)
                        REFERENCES temporal_relations(relation_id)
                        ON DELETE CASCADE
                );
                """
            )
            conn.commit()

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> TemporalSourceReference:
        return TemporalSourceReference(
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_revision=int(row["source_revision"]),
            source_chapter_number=(
                int(row["source_chapter_number"])
                if row["source_chapter_number"] is not None
                else None
            ),
        )

    def _event_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> TemporalEvent:
        participants = conn.execute(
            """
            SELECT entity_id FROM temporal_event_participants
            WHERE event_id = ? ORDER BY participant_order, entity_id
            """,
            (row["event_id"],),
        ).fetchall()
        return TemporalEvent(
            event_id=row["event_id"],
            novel_id=row["novel_id"],
            event_type=row["event_type"],
            context_type=row["context_type"],
            title=row["title"],
            summary=row["summary"],
            participant_entity_ids=[item["entity_id"] for item in participants],
            location_entity_id=row["location_entity_id"],
            start_chapter=int(row["start_chapter"]),
            end_chapter=(
                int(row["end_chapter"])
                if row["end_chapter"] is not None
                else None
            ),
            source=self._source_from_row(row),
            confidence=float(row["confidence"]),
            metadata=_json_load(row["metadata_json"], {}),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _relation_from_row(row: sqlite3.Row) -> TemporalRelation:
        return TemporalRelation(
            relation_id=row["relation_id"],
            novel_id=row["novel_id"],
            subject_entity_id=row["subject_entity_id"],
            predicate=row["predicate"],
            object_entity_id=row["object_entity_id"],
            context_type=row["context_type"],
            description=row["description"],
            valid_from_chapter=int(row["valid_from_chapter"]),
            valid_to_chapter=(
                int(row["valid_to_chapter"])
                if row["valid_to_chapter"] is not None
                else None
            ),
            source=TemporalGraphStorage._source_from_row(row),
            confidence=float(row["confidence"]),
            metadata=_json_load(row["metadata_json"], {}),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _replace_participants(
        conn: sqlite3.Connection,
        event_id: str,
        entity_ids: list[str],
    ) -> None:
        conn.execute(
            "DELETE FROM temporal_event_participants WHERE event_id = ?",
            (event_id,),
        )
        conn.executemany(
            """
            INSERT INTO temporal_event_participants(
                event_id, entity_id, participant_order
            ) VALUES (?, ?, ?)
            """,
            [
                (event_id, entity_id, index)
                for index, entity_id in enumerate(entity_ids)
            ],
        )

    @staticmethod
    def _insert_event_revision(
        conn: sqlite3.Connection,
        event: TemporalEvent,
    ) -> None:
        conn.execute(
            """
            INSERT INTO temporal_event_revisions(
                event_id, novel_id, revision, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.novel_id,
                event.revision,
                _json_dump(event.model_dump(mode="json")),
                event.updated_at,
            ),
        )

    @staticmethod
    def _insert_relation_revision(
        conn: sqlite3.Connection,
        relation: TemporalRelation,
    ) -> None:
        conn.execute(
            """
            INSERT INTO temporal_relation_revisions(
                relation_id, novel_id, revision, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                relation.relation_id,
                relation.novel_id,
                relation.revision,
                _json_dump(relation.model_dump(mode="json")),
                relation.updated_at,
            ),
        )

    def create_event(
        self,
        novel_id: str,
        payload: TemporalEventCreate,
    ) -> TemporalEvent:
        event_id = payload.event_id or f"evt_{uuid.uuid4().hex}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO temporal_events(
                        event_id, novel_id, event_type, context_type, title,
                        summary, location_entity_id, start_chapter, end_chapter,
                        source_type, source_id, source_revision,
                        source_chapter_number, confidence, metadata_json,
                        revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        event_id,
                        novel_id,
                        payload.event_type,
                        payload.context_type,
                        payload.title,
                        payload.summary,
                        payload.location_entity_id,
                        payload.start_chapter,
                        payload.end_chapter,
                        payload.source.source_type,
                        payload.source.source_id,
                        payload.source.source_revision,
                        payload.source.source_chapter_number,
                        payload.confidence,
                        _json_dump(payload.metadata),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise TemporalGraphConflictError(
                    f"Temporal Event already exists: {event_id}"
                ) from exc
            self._replace_participants(
                conn,
                event_id,
                payload.participant_entity_ids,
            )
            row = conn.execute(
                "SELECT * FROM temporal_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            event = self._event_from_row(conn, row)
            self._insert_event_revision(conn, event)
            conn.commit()
        return event

    def get_event(self, novel_id: str, event_id: str) -> TemporalEvent:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM temporal_events
                WHERE novel_id = ? AND event_id = ?
                """,
                (novel_id, event_id),
            ).fetchone()
            if row is None:
                raise TemporalGraphNotFoundError(
                    f"Temporal Event not found: {event_id}"
                )
            return self._event_from_row(conn, row)

    def update_event(
        self,
        novel_id: str,
        event_id: str,
        payload: TemporalEventUpdate,
    ) -> TemporalEvent:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM temporal_events
                WHERE novel_id = ? AND event_id = ?
                """,
                (novel_id, event_id),
            ).fetchone()
            if row is None:
                raise TemporalGraphNotFoundError(
                    f"Temporal Event not found: {event_id}"
                )
            if int(row["revision"]) != payload.expected_revision:
                raise TemporalGraphConflictError(
                    "Temporal Event revision conflict: "
                    f"expected={payload.expected_revision}, "
                    f"actual={row['revision']}"
                )
            current = self._event_from_row(conn, row)
            values = payload.model_dump(exclude_unset=True)
            source = payload.source
            participants = values.pop(
                "participant_entity_ids",
                current.participant_entity_ids,
            )
            values.pop("expected_revision", None)
            values.pop("source", None)
            merged = current.model_dump()
            merged.update(values)
            start = int(merged["start_chapter"])
            end = merged.get("end_chapter")
            if end is not None and int(end) < start:
                raise TemporalGraphConflictError(
                    "Temporal Event end_chapter must be >= start_chapter"
                )
            now = _utc_now()
            conn.execute(
                """
                UPDATE temporal_events SET
                    event_type = ?, context_type = ?, title = ?, summary = ?,
                    location_entity_id = ?, start_chapter = ?, end_chapter = ?,
                    source_type = ?, source_id = ?, source_revision = ?,
                    source_chapter_number = ?, confidence = ?, metadata_json = ?,
                    revision = revision + 1, updated_at = ?
                WHERE novel_id = ? AND event_id = ?
                """,
                (
                    merged["event_type"],
                    merged["context_type"],
                    merged["title"],
                    merged["summary"],
                    merged.get("location_entity_id"),
                    start,
                    end,
                    source.source_type,
                    source.source_id,
                    source.source_revision,
                    source.source_chapter_number,
                    merged["confidence"],
                    _json_dump(merged["metadata"]),
                    now,
                    novel_id,
                    event_id,
                ),
            )
            self._replace_participants(conn, event_id, participants)
            updated_row = conn.execute(
                "SELECT * FROM temporal_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            event = self._event_from_row(conn, updated_row)
            self._insert_event_revision(conn, event)
            conn.commit()
        return event

    def list_events(
        self,
        novel_id: str,
        *,
        active_entity_ids: list[str] | None = None,
        as_of_chapter: int | None = None,
        include_historical: bool = False,
        context_types: list[str] | None = None,
        event_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[TemporalEvent]:
        clauses = ["e.novel_id = ?"]
        params: list[Any] = [novel_id]
        clauses.append(
            "COALESCE(json_extract(e.metadata_json, '$.retracted'), 0) = 0"
        )
        if as_of_chapter is not None:
            clauses.append("e.start_chapter <= ?")
            params.append(as_of_chapter)
            if not include_historical:
                clauses.append("(e.end_chapter IS NULL OR e.end_chapter >= ?)")
                params.append(as_of_chapter)
        elif not include_historical:
            clauses.append("e.end_chapter IS NULL")
        if context_types:
            placeholders = ",".join("?" for _ in context_types)
            clauses.append(f"e.context_type IN ({placeholders})")
            params.extend(context_types)
        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            clauses.append(f"e.event_type IN ({placeholders})")
            params.extend(event_types)
        if active_entity_ids:
            placeholders = ",".join("?" for _ in active_entity_ids)
            clauses.append(
                "(" 
                f"e.location_entity_id IN ({placeholders}) OR EXISTS ("
                "SELECT 1 FROM temporal_event_participants p "
                "WHERE p.event_id = e.event_id "
                f"AND p.entity_id IN ({placeholders})))"
            )
            params.extend(active_entity_ids)
            params.extend(active_entity_ids)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.* FROM temporal_events e
                WHERE {' AND '.join(clauses)}
                ORDER BY e.start_chapter DESC, e.event_id
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [self._event_from_row(conn, row) for row in rows]

    def list_event_revisions(
        self,
        novel_id: str,
        event_id: str,
        *,
        limit: int = 100,
    ) -> list[TemporalEventRevision]:
        self.get_event(novel_id, event_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM temporal_event_revisions
                WHERE novel_id = ? AND event_id = ?
                ORDER BY revision DESC LIMIT ?
                """,
                (novel_id, event_id, limit),
            ).fetchall()
        return [
            TemporalEventRevision(
                event_id=row["event_id"],
                novel_id=row["novel_id"],
                revision=int(row["revision"]),
                snapshot=TemporalEvent.model_validate(
                    _json_load(row["snapshot_json"], {})
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_relation(
        self,
        novel_id: str,
        payload: TemporalRelationCreate,
    ) -> TemporalRelation:
        relation_id = payload.relation_id or f"rel_{uuid.uuid4().hex}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO temporal_relations(
                        relation_id, novel_id, subject_entity_id, predicate,
                        object_entity_id, context_type, description,
                        valid_from_chapter, valid_to_chapter, source_type,
                        source_id, source_revision, source_chapter_number,
                        confidence, metadata_json, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        relation_id,
                        novel_id,
                        payload.subject_entity_id,
                        payload.predicate,
                        payload.object_entity_id,
                        payload.context_type,
                        payload.description,
                        payload.valid_from_chapter,
                        payload.valid_to_chapter,
                        payload.source.source_type,
                        payload.source.source_id,
                        payload.source.source_revision,
                        payload.source.source_chapter_number,
                        payload.confidence,
                        _json_dump(payload.metadata),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise TemporalGraphConflictError(
                    f"Temporal Relation already exists: {relation_id}"
                ) from exc
            row = conn.execute(
                "SELECT * FROM temporal_relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
            relation = self._relation_from_row(row)
            self._insert_relation_revision(conn, relation)
            conn.commit()
        return relation

    def get_relation(
        self,
        novel_id: str,
        relation_id: str,
    ) -> TemporalRelation:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM temporal_relations
                WHERE novel_id = ? AND relation_id = ?
                """,
                (novel_id, relation_id),
            ).fetchone()
        if row is None:
            raise TemporalGraphNotFoundError(
                f"Temporal Relation not found: {relation_id}"
            )
        return self._relation_from_row(row)

    def update_relation(
        self,
        novel_id: str,
        relation_id: str,
        payload: TemporalRelationUpdate,
    ) -> TemporalRelation:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM temporal_relations
                WHERE novel_id = ? AND relation_id = ?
                """,
                (novel_id, relation_id),
            ).fetchone()
            if row is None:
                raise TemporalGraphNotFoundError(
                    f"Temporal Relation not found: {relation_id}"
                )
            if int(row["revision"]) != payload.expected_revision:
                raise TemporalGraphConflictError(
                    "Temporal Relation revision conflict: "
                    f"expected={payload.expected_revision}, "
                    f"actual={row['revision']}"
                )
            current = self._relation_from_row(row)
            values = payload.model_dump(exclude_unset=True)
            source = payload.source
            values.pop("expected_revision", None)
            values.pop("source", None)
            merged = current.model_dump()
            merged.update(values)
            start = int(merged["valid_from_chapter"])
            end = merged.get("valid_to_chapter")
            if end is not None and int(end) < start:
                raise TemporalGraphConflictError(
                    "Temporal Relation valid_to_chapter must be "
                    ">= valid_from_chapter"
                )
            now = _utc_now()
            conn.execute(
                """
                UPDATE temporal_relations SET
                    subject_entity_id = ?, predicate = ?, object_entity_id = ?,
                    context_type = ?, description = ?, valid_from_chapter = ?,
                    valid_to_chapter = ?, source_type = ?, source_id = ?,
                    source_revision = ?, source_chapter_number = ?,
                    confidence = ?, metadata_json = ?,
                    revision = revision + 1, updated_at = ?
                WHERE novel_id = ? AND relation_id = ?
                """,
                (
                    merged["subject_entity_id"],
                    merged["predicate"],
                    merged["object_entity_id"],
                    merged["context_type"],
                    merged["description"],
                    start,
                    end,
                    source.source_type,
                    source.source_id,
                    source.source_revision,
                    source.source_chapter_number,
                    merged["confidence"],
                    _json_dump(merged["metadata"]),
                    now,
                    novel_id,
                    relation_id,
                ),
            )
            updated_row = conn.execute(
                "SELECT * FROM temporal_relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
            relation = self._relation_from_row(updated_row)
            self._insert_relation_revision(conn, relation)
            conn.commit()
        return relation

    def list_relations(
        self,
        novel_id: str,
        *,
        active_entity_ids: list[str] | None = None,
        as_of_chapter: int | None = None,
        include_historical: bool = False,
        context_types: list[str] | None = None,
        predicates: list[str] | None = None,
        limit: int = 100,
    ) -> list[TemporalRelation]:
        clauses = ["novel_id = ?"]
        params: list[Any] = [novel_id]
        clauses.append(
            "COALESCE(json_extract(metadata_json, '$.retracted'), 0) = 0"
        )
        if as_of_chapter is not None:
            clauses.append("valid_from_chapter <= ?")
            params.append(as_of_chapter)
            if not include_historical:
                clauses.append("(valid_to_chapter IS NULL OR valid_to_chapter >= ?)")
                params.append(as_of_chapter)
        elif not include_historical:
            clauses.append("valid_to_chapter IS NULL")
        if context_types:
            placeholders = ",".join("?" for _ in context_types)
            clauses.append(f"context_type IN ({placeholders})")
            params.extend(context_types)
        if predicates:
            placeholders = ",".join("?" for _ in predicates)
            clauses.append(f"predicate IN ({placeholders})")
            params.extend(predicates)
        if active_entity_ids:
            placeholders = ",".join("?" for _ in active_entity_ids)
            clauses.append(
                f"(subject_entity_id IN ({placeholders}) "
                f"OR object_entity_id IN ({placeholders}))"
            )
            params.extend(active_entity_ids)
            params.extend(active_entity_ids)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM temporal_relations
                WHERE {' AND '.join(clauses)}
                ORDER BY valid_from_chapter DESC, relation_id
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._relation_from_row(row) for row in rows]

    def list_relation_revisions(
        self,
        novel_id: str,
        relation_id: str,
        *,
        limit: int = 100,
    ) -> list[TemporalRelationRevision]:
        self.get_relation(novel_id, relation_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM temporal_relation_revisions
                WHERE novel_id = ? AND relation_id = ?
                ORDER BY revision DESC LIMIT ?
                """,
                (novel_id, relation_id, limit),
            ).fetchall()
        return [
            TemporalRelationRevision(
                relation_id=row["relation_id"],
                novel_id=row["novel_id"],
                revision=int(row["revision"]),
                snapshot=TemporalRelation.model_validate(
                    _json_load(row["snapshot_json"], {})
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]
