from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import (
    ExternalKnowledgeChunk,
    ExternalKnowledgeSource,
    ExternalKnowledgeSourceCreate,
    ExternalKnowledgeSourceRevision,
    ExternalKnowledgeSourceUpdate,
)


class ExternalKnowledgeError(RuntimeError):
    pass


class ExternalKnowledgeNotFoundError(ExternalKnowledgeError):
    pass


class ExternalKnowledgeConflictError(ExternalKnowledgeError):
    pass


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SQLiteExternalKnowledgeStorage:
    """Authoritative store isolated from novel Memory and Canon data."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(
            db_path
            or os.getenv(
                "EXTERNAL_KNOWLEDGE_DB_PATH",
                "/app/data/external_knowledge.db",
            )
        )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_knowledge_sources (
                    source_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    knowledge_base_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    current_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, knowledge_base_id, source_uri)
                );

                CREATE INDEX IF NOT EXISTS idx_external_sources_scope
                ON external_knowledge_sources (
                    user_id,
                    knowledge_base_id,
                    updated_at DESC
                );

                CREATE TABLE IF NOT EXISTS external_knowledge_revisions (
                    source_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    author TEXT,
                    published_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, revision),
                    FOREIGN KEY (source_id)
                        REFERENCES external_knowledge_sources(source_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS external_knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    chunk_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (source_id, source_revision, chunk_number),
                    FOREIGN KEY (source_id, source_revision)
                        REFERENCES external_knowledge_revisions(
                            source_id,
                            revision
                        )
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_external_chunks_current
                ON external_knowledge_chunks (
                    source_id,
                    source_revision,
                    chunk_number
                );
                """
            )
            conn.commit()

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> ExternalKnowledgeSource:
        return ExternalKnowledgeSource(
            source_id=str(row["source_id"]),
            user_id=str(row["user_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            source_type=str(row["source_type"]),
            source_uri=str(row["source_uri"]),
            current_revision=int(row["current_revision"]),
            title=str(row["title"]),
            content=str(row["content"]),
            content_hash=str(row["content_hash"]),
            author=(
                str(row["author"])
                if row["author"] is not None
                else None
            ),
            published_at=(
                str(row["published_at"])
                if row["published_at"] is not None
                else None
            ),
            metadata=_json_load(row["metadata_json"]),
            created_at=str(row["source_created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _revision_from_row(
        row: sqlite3.Row,
    ) -> ExternalKnowledgeSourceRevision:
        return ExternalKnowledgeSourceRevision(
            source_id=str(row["source_id"]),
            revision=int(row["revision"]),
            title=str(row["title"]),
            content=str(row["content"]),
            content_hash=str(row["content_hash"]),
            author=(
                str(row["author"])
                if row["author"] is not None
                else None
            ),
            published_at=(
                str(row["published_at"])
                if row["published_at"] is not None
                else None
            ),
            metadata=_json_load(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _source_select() -> str:
        return """
            SELECT
                s.source_id,
                s.user_id,
                s.knowledge_base_id,
                s.source_type,
                s.source_uri,
                s.current_revision,
                s.created_at AS source_created_at,
                s.updated_at,
                r.title,
                r.content,
                r.content_hash,
                r.author,
                r.published_at,
                r.metadata_json
            FROM external_knowledge_sources AS s
            JOIN external_knowledge_revisions AS r
              ON r.source_id = s.source_id
             AND r.revision = s.current_revision
        """

    @staticmethod
    def _insert_chunks(
        conn: sqlite3.Connection,
        *,
        source_id: str,
        revision: int,
        chunks: list[tuple[str, int, int]],
        created_at: str,
    ) -> list[ExternalKnowledgeChunk]:
        result: list[ExternalKnowledgeChunk] = []
        namespace = uuid.UUID(source_id)

        for chunk_number, (content, start_char, end_char) in enumerate(
            chunks,
            start=1,
        ):
            digest = _content_hash(content)
            chunk_id = str(
                uuid.uuid5(
                    namespace,
                    f"revision:{revision}:chunk:{chunk_number}:{digest}",
                )
            )
            conn.execute(
                """
                INSERT INTO external_knowledge_chunks (
                    chunk_id,
                    source_id,
                    source_revision,
                    chunk_number,
                    content,
                    start_char,
                    end_char,
                    content_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    source_id,
                    revision,
                    chunk_number,
                    content,
                    start_char,
                    end_char,
                    digest,
                    created_at,
                ),
            )
            result.append(
                ExternalKnowledgeChunk(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    source_revision=revision,
                    chunk_number=chunk_number,
                    content=content,
                    start_char=start_char,
                    end_char=end_char,
                    content_hash=digest,
                    created_at=created_at,
                )
            )
        return result

    async def create(
        self,
        payload: ExternalKnowledgeSourceCreate,
        chunks: list[tuple[str, int, int]],
    ) -> tuple[ExternalKnowledgeSource, list[ExternalKnowledgeChunk]]:
        source_id = str(uuid.uuid4())
        now = _utc_now().isoformat()
        content_hash = _content_hash(payload.content)

        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO external_knowledge_sources (
                        source_id,
                        user_id,
                        knowledge_base_id,
                        source_type,
                        source_uri,
                        current_revision,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        source_id,
                        payload.user_id,
                        payload.knowledge_base_id,
                        payload.source_type.value,
                        payload.source_uri,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO external_knowledge_revisions (
                        source_id,
                        revision,
                        title,
                        content,
                        content_hash,
                        author,
                        published_at,
                        metadata_json,
                        created_at
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        payload.title,
                        payload.content,
                        content_hash,
                        payload.author,
                        payload.published_at,
                        _json_dump(payload.metadata),
                        now,
                    ),
                )
                inserted_chunks = self._insert_chunks(
                    conn,
                    source_id=source_id,
                    revision=1,
                    chunks=chunks,
                    created_at=now,
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ExternalKnowledgeConflictError(
                "An external knowledge source with this URI already exists "
                "in the selected knowledge base."
            ) from exc

        source = await self.get(
            source_id,
            payload.user_id,
            payload.knowledge_base_id,
        )
        assert source is not None
        return source, inserted_chunks

    async def get(
        self,
        source_id: str,
        user_id: str,
        knowledge_base_id: str,
    ) -> ExternalKnowledgeSource | None:
        with self._connect() as conn:
            row = conn.execute(
                self._source_select()
                + """
                    WHERE s.source_id = ?
                      AND s.user_id = ?
                      AND s.knowledge_base_id = ?
                """,
                (source_id, user_id, knowledge_base_id),
            ).fetchone()
        return self._source_from_row(row) if row else None

    async def list_sources(
        self,
        user_id: str,
        knowledge_base_id: str,
    ) -> list[ExternalKnowledgeSource]:
        with self._connect() as conn:
            rows = conn.execute(
                self._source_select()
                + """
                    WHERE s.user_id = ?
                      AND s.knowledge_base_id = ?
                    ORDER BY s.updated_at DESC, s.source_id
                """,
                (user_id, knowledge_base_id),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    async def list_revisions(
        self,
        source_id: str,
        user_id: str,
        knowledge_base_id: str,
    ) -> list[ExternalKnowledgeSourceRevision]:
        source = await self.get(source_id, user_id, knowledge_base_id)
        if source is None:
            raise ExternalKnowledgeNotFoundError(source_id)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM external_knowledge_revisions
                WHERE source_id = ?
                ORDER BY revision DESC
                """,
                (source_id,),
            ).fetchall()
        return [self._revision_from_row(row) for row in rows]

    async def update(
        self,
        source_id: str,
        payload: ExternalKnowledgeSourceUpdate,
        chunks: list[tuple[str, int, int]],
    ) -> tuple[
        ExternalKnowledgeSource,
        list[ExternalKnowledgeChunk],
        list[str],
    ]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                self._source_select()
                + """
                    WHERE s.source_id = ?
                      AND s.user_id = ?
                      AND s.knowledge_base_id = ?
                """,
                (
                    source_id,
                    payload.user_id,
                    payload.knowledge_base_id,
                ),
            ).fetchone()
            if row is None:
                raise ExternalKnowledgeNotFoundError(source_id)

            current = self._source_from_row(row)
            if current.current_revision != payload.expected_revision:
                raise ExternalKnowledgeConflictError(
                    "External knowledge source revision conflict: "
                    f"expected={payload.expected_revision}, "
                    f"actual={current.current_revision}"
                )

            old_chunk_rows = conn.execute(
                """
                SELECT chunk_id
                FROM external_knowledge_chunks
                WHERE source_id = ? AND source_revision = ?
                ORDER BY chunk_number
                """,
                (source_id, current.current_revision),
            ).fetchall()
            old_chunk_ids = [str(item["chunk_id"]) for item in old_chunk_rows]

            fields = payload.model_fields_set
            title = payload.title if "title" in fields else current.title
            content = payload.content if "content" in fields else current.content
            author = payload.author if "author" in fields else current.author
            published_at = (
                payload.published_at
                if "published_at" in fields
                else current.published_at
            )
            metadata = (
                payload.metadata
                if "metadata" in fields
                else current.metadata
            )
            assert title is not None
            assert content is not None
            assert metadata is not None

            revision = current.current_revision + 1
            now = _utc_now().isoformat()
            conn.execute(
                """
                INSERT INTO external_knowledge_revisions (
                    source_id,
                    revision,
                    title,
                    content,
                    content_hash,
                    author,
                    published_at,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    revision,
                    title,
                    content,
                    _content_hash(content),
                    author,
                    published_at,
                    _json_dump(metadata),
                    now,
                ),
            )
            inserted_chunks = self._insert_chunks(
                conn,
                source_id=source_id,
                revision=revision,
                chunks=chunks,
                created_at=now,
            )
            conn.execute(
                """
                UPDATE external_knowledge_sources
                SET current_revision = ?, updated_at = ?
                WHERE source_id = ?
                """,
                (revision, now, source_id),
            )
            conn.commit()

        source = await self.get(
            source_id,
            payload.user_id,
            payload.knowledge_base_id,
        )
        assert source is not None
        return source, inserted_chunks, old_chunk_ids

    async def load_current_chunks(
        self,
        chunk_ids: list[str],
        user_id: str,
        knowledge_base_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not chunk_ids or not knowledge_base_ids:
            return []
        chunk_marks = ",".join("?" for _ in chunk_ids)
        base_marks = ",".join("?" for _ in knowledge_base_ids)
        sql = f"""
            SELECT
                c.chunk_id,
                c.source_id,
                c.source_revision,
                c.chunk_number,
                c.content,
                c.start_char,
                c.end_char,
                s.user_id,
                s.knowledge_base_id,
                s.source_type,
                s.source_uri,
                r.title,
                r.author,
                r.published_at
            FROM external_knowledge_chunks AS c
            JOIN external_knowledge_sources AS s
              ON s.source_id = c.source_id
             AND s.current_revision = c.source_revision
            JOIN external_knowledge_revisions AS r
              ON r.source_id = c.source_id
             AND r.revision = c.source_revision
            WHERE c.chunk_id IN ({chunk_marks})
              AND s.user_id = ?
              AND s.knowledge_base_id IN ({base_marks})
        """
        with self._connect() as conn:
            rows = conn.execute(
                sql,
                (
                    *chunk_ids,
                    user_id,
                    *knowledge_base_ids,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    async def list_current_chunks(self) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.content
                FROM external_knowledge_chunks AS c
                JOIN external_knowledge_sources AS s
                  ON s.source_id = c.source_id
                 AND s.current_revision = c.source_revision
                ORDER BY c.chunk_id
                """
            ).fetchall()
        return [
            (str(row["chunk_id"]), str(row["content"]))
            for row in rows
        ]

    async def delete(
        self,
        source_id: str,
        user_id: str,
        knowledge_base_id: str,
    ) -> tuple[int, int, list[str]]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source = conn.execute(
                """
                SELECT current_revision
                FROM external_knowledge_sources
                WHERE source_id = ?
                  AND user_id = ?
                  AND knowledge_base_id = ?
                """,
                (source_id, user_id, knowledge_base_id),
            ).fetchone()
            if source is None:
                raise ExternalKnowledgeNotFoundError(source_id)

            revision_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM external_knowledge_revisions
                    WHERE source_id = ?
                    """,
                    (source_id,),
                ).fetchone()[0]
            )
            chunk_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM external_knowledge_chunks
                    WHERE source_id = ?
                    """,
                    (source_id,),
                ).fetchone()[0]
            )
            current_rows = conn.execute(
                """
                SELECT chunk_id
                FROM external_knowledge_chunks
                WHERE source_id = ? AND source_revision = ?
                """,
                (source_id, int(source["current_revision"])),
            ).fetchall()
            current_chunk_ids = [str(row["chunk_id"]) for row in current_rows]
            conn.execute(
                "DELETE FROM external_knowledge_sources WHERE source_id = ?",
                (source_id,),
            )
            conn.commit()
        return revision_count, chunk_count, current_chunk_ids
