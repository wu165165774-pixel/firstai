import json
import os
import sqlite3
import uuid

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..schemas import (
    MemoryItem,
    MemoryLifecycleEvent,
    MemoryTier,
)
from ..score import calculate_score
from .base import BaseMemoryStorage


class MemoryNotFoundError(LookupError):
    pass


class MemoryLifecycleConflictError(RuntimeError):
    pass


class SQLiteMemoryStorage(BaseMemoryStorage):

    def __init__(
        self,
        db_path: str | None = None,
    ):

        self.db_path = (
            db_path
            or os.getenv(
                "MEMORY_DB_PATH",
                "/app/data/memory.db",
            )
        )

        Path(self.db_path).parent.mkdir(
            parents=True,   
            exist_ok=True
        )

        self._init_db()

    def _get_connection(self):

        conn = sqlite3.connect(
            self.db_path
        )

        conn.row_factory = sqlite3.Row

        return conn

    def _column_exists(
        self,
        conn,
        column
    ):

        rows = conn.execute(
            "PRAGMA table_info(memories)"
        ).fetchall()

        names = [
            r["name"]
            for r in rows
        ]

        return column in names

    @staticmethod
    def _tier_value(value: Any) -> str:

        if hasattr(value, "value"):
            value = value.value

        return str(value or MemoryTier.LONG_TERM.value)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:

        if not value:
            return None

        return datetime.fromisoformat(str(value))

    @classmethod
    def _row_to_memory(cls, row: sqlite3.Row) -> MemoryItem:

        keys = set(row.keys())
        metadata: dict[str, Any] = {}

        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        return MemoryItem(
            id=row["id"],
            user_id=row["user_id"],
            novel_id=row["novel_id"],
            memory_type=row["memory_type"],
            memory_tier=(
                row["memory_tier"]
                if "memory_tier" in keys
                else MemoryTier.LONG_TERM.value
            ),
            session_id=(
                row["session_id"]
                if "session_id" in keys
                else None
            ),
            content=row["content"],
            importance=row["importance"],
            hit_count=(
                row["hit_count"]
                if row["hit_count"] is not None
                else 1
            ),
            revision=(
                row["revision"]
                if "revision" in keys
                and row["revision"] is not None
                else 1
            ),
            score=(
                row["score"]
                if row["score"] is not None
                else 0.0
            ),
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
            last_accessed_at=cls._parse_datetime(
                row["last_accessed_at"]
            ),
            expires_at=(
                cls._parse_datetime(row["expires_at"])
                if "expires_at" in keys
                else None
            ),
            metadata=metadata,
        )

    @staticmethod
    def _row_to_event(
        row: sqlite3.Row,
    ) -> MemoryLifecycleEvent:

        try:
            payload = json.loads(row["payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}

        return MemoryLifecycleEvent(
            event_id=row["event_id"],
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            novel_id=row["novel_id"],
            event_type=row["event_type"],
            from_tier=row["from_tier"],
            to_tier=row["to_tier"],
            reason=row["reason"],
            payload=payload,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @classmethod
    def _append_lifecycle_event(
        cls,
        conn: sqlite3.Connection,
        *,
        memory: MemoryItem,
        event_type: str,
        from_tier: str | None,
        to_tier: str | None,
        reason: str,
        payload: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> MemoryLifecycleEvent:

        event = MemoryLifecycleEvent(
            event_id=str(uuid.uuid4()),
            memory_id=str(memory.id),
            user_id=memory.user_id,
            novel_id=memory.novel_id,
            event_type=event_type,
            from_tier=from_tier,
            to_tier=to_tier,
            reason=reason,
            payload=payload or {},
            created_at=created_at or datetime.utcnow(),
        )

        conn.execute(
            """
            INSERT INTO memory_lifecycle_events (
                event_id,
                memory_id,
                user_id,
                novel_id,
                event_type,
                from_tier,
                to_tier,
                reason,
                payload,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.memory_id,
                event.user_id,
                event.novel_id,
                event.event_type,
                cls._tier_value(event.from_tier)
                if event.from_tier is not None
                else None,
                cls._tier_value(event.to_tier)
                if event.to_tier is not None
                else None,
                event.reason,
                json.dumps(event.payload, ensure_ascii=False),
                event.created_at.isoformat(),
            ),
        )

        return event

    def _init_db(self):

        with self._get_connection() as conn:

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (

                    id TEXT PRIMARY KEY,

                    user_id TEXT NOT NULL,

                    novel_id TEXT NOT NULL,

                    memory_type TEXT NOT NULL,

                    content TEXT NOT NULL,

                    importance REAL NOT NULL DEFAULT 0.5,

                    hit_count INTEGER DEFAULT 1,

                    score REAL DEFAULT 0,

                    created_at TEXT NOT NULL,

                    updated_at TEXT,

                    last_accessed_at TEXT,

                    metadata TEXT,

                    memory_tier TEXT NOT NULL DEFAULT 'long_term',

                    session_id TEXT,

                    expires_at TEXT,

                    revision INTEGER NOT NULL DEFAULT 1

                )
                """
            )

            columns = [
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(memories)"
                ).fetchall()
            ]

            upgrades = {

                "hit_count":
                    "ALTER TABLE memories ADD COLUMN hit_count INTEGER DEFAULT 1",

                "score":
                    "ALTER TABLE memories ADD COLUMN score REAL DEFAULT 0",

                "updated_at":
                    "ALTER TABLE memories ADD COLUMN updated_at TEXT",

                "last_accessed_at":
                    "ALTER TABLE memories ADD COLUMN last_accessed_at TEXT",

                "memory_tier":
                    "ALTER TABLE memories ADD COLUMN memory_tier TEXT NOT NULL DEFAULT 'long_term'",

                "session_id":
                    "ALTER TABLE memories ADD COLUMN session_id TEXT",

                "expires_at":
                    "ALTER TABLE memories ADD COLUMN expires_at TEXT",

                "revision":
                    "ALTER TABLE memories ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",

            }

            for column, sql in upgrades.items():

                if column not in columns:

                    print(f"[DB Upgrade] add column -> {column}")

                    conn.execute(sql)

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_tier_scope
                ON memories (
                    user_id,
                    novel_id,
                    memory_tier,
                    session_id
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_expiration
                ON memories (memory_tier, expires_at)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_tier TEXT,
                    to_tier TEXT,
                    reason TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_events
                ON memory_lifecycle_events (memory_id, created_at)
                """
            )

            conn.commit()

    async def save(
        self,
        memory: MemoryItem
    ):

        if memory.id is None:
            memory.id = str(uuid.uuid4())

        now = datetime.utcnow()
        memory.created_at = memory.created_at or now
        memory.updated_at = memory.updated_at or now
        memory.last_accessed_at = memory.last_accessed_at or now
        memory.revision = max(int(memory.revision), 1)

        tier = self._tier_value(memory.memory_tier)
        if tier == MemoryTier.SESSION.value:
            memory.expires_at = (
                memory.expires_at
                or now + timedelta(hours=24)
            )
        elif tier == MemoryTier.WORKING.value:
            memory.expires_at = (
                memory.expires_at
                or now + timedelta(days=30)
            )
        else:
            memory.expires_at = None

        memory.score = calculate_score(memory)
        if memory.hit_count is None:
            memory.hit_count = 0

        metadata = json.dumps(
            memory.metadata or {},
            ensure_ascii=False,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    id,
                    user_id,
                    novel_id,
                    memory_type,
                    content,
                    importance,
                    hit_count,
                    score,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    metadata,
                    memory_tier,
                    session_id,
                    expires_at,
                    revision
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    memory.id,
                    memory.user_id,
                    memory.novel_id,
                    memory.memory_type.value
                    if hasattr(memory.memory_type, "value")
                    else memory.memory_type,
                    memory.content,
                    memory.importance,
                    memory.hit_count,
                    memory.score,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                    memory.last_accessed_at.isoformat(),
                    metadata,
                    tier,
                    memory.session_id,
                    memory.expires_at.isoformat()
                    if memory.expires_at
                    else None,
                    memory.revision,
                ),
            )

            self._append_lifecycle_event(
                conn,
                memory=memory,
                event_type="memory_created",
                from_tier=None,
                to_tier=tier,
                reason="Memory created.",
                payload={
                    "memory_type": (
                        memory.memory_type.value
                        if hasattr(memory.memory_type, "value")
                        else str(memory.memory_type)
                    ),
                    "session_id": memory.session_id,
                    "expires_at": (
                        memory.expires_at.isoformat()
                        if memory.expires_at
                        else None
                    ),
                },
                created_at=now,
            )
            conn.commit()

        return memory

    async def delete(
        self,
        memory_id: str
    ):

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    novel_id,
                    memory_type,
                    content,
                    importance,
                    hit_count,
                    score,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    metadata,
                    memory_tier,
                    session_id,
                    expires_at,
                    revision
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()

            if row is None:
                return None

            memory = self._row_to_memory(row)
            conn.execute(
                """
                DELETE FROM memories
                WHERE id=?
                """,
                (memory_id,)
            )

            self._append_lifecycle_event(
                conn,
                memory=memory,
                event_type="memory_deleted",
                from_tier=self._tier_value(memory.memory_tier),
                to_tier=None,
                reason="Memory explicitly deleted.",
                payload={"revision": memory.revision},
            )

            conn.commit()

        return {
            "id": memory_id
        }

    async def update(
        self,
        memory: MemoryItem
    ):

        now = datetime.utcnow()
        memory.updated_at = now

        if memory.last_accessed_at is None:
            memory.last_accessed_at = now

        tier = self._tier_value(memory.memory_tier)
        if tier == MemoryTier.SESSION.value:
            memory.expires_at = now + timedelta(hours=24)
        elif tier == MemoryTier.WORKING.value:
            memory.expires_at = now + timedelta(days=30)
        else:
            memory.expires_at = None

        memory.score = calculate_score(memory)

        memory.revision = max(
            int(memory.revision or 1),
            1,
        ) + 1


        metadata = json.dumps(
            memory.metadata or {},
            ensure_ascii=False
        )

        with self._get_connection() as conn:

            conn.execute(
                """
                UPDATE memories

                SET

                    content=?,
                    importance=?,
                    hit_count=?,
                    score=?,
                    updated_at=?,
                    last_accessed_at=?,
                    metadata=?,
                    expires_at=?,
                    revision=?

                WHERE id=?
                """,

                (

                    memory.content,
                    memory.importance,
                    memory.hit_count,
                    memory.score,
                    memory.updated_at.isoformat(),
                    memory.last_accessed_at.isoformat(),
                    metadata,
                    memory.expires_at.isoformat()
                    if memory.expires_at
                    else None,
                    memory.revision,
                    memory.id

                )

            )

            self._append_lifecycle_event(
                conn,
                memory=memory,
                event_type="memory_reinforced",
                from_tier=self._tier_value(memory.memory_tier),
                to_tier=self._tier_value(memory.memory_tier),
                reason="Duplicate memory reinforced.",
                payload={
                    "hit_count": memory.hit_count,
                    "importance": memory.importance,
                    "revision": memory.revision,
                },
                created_at=now,
            )

            conn.commit()

        return memory
    
    async def query(
        self,
        user_id: str,
        novel_id: str,
        memory_type=None,
        memory_tier=None,
        session_id: str | None = None,
        include_expired: bool = False,
    ):

        sql = """
            SELECT
                id,
                user_id,
                novel_id,
                memory_type,
                content,
                importance,
                hit_count,
                score,
                created_at,
                updated_at,
                last_accessed_at,
                metadata,
                memory_tier,
                session_id,
                expires_at,
                revision
            FROM memories
            WHERE user_id = ?
              AND novel_id = ?
        """

        params: list[Any] = [user_id, novel_id]

        if memory_type is not None:
            sql += " AND memory_type = ?"
            params.append(
                memory_type.value
                if hasattr(memory_type, "value")
                else str(memory_type)
            )

        if memory_tier is not None:
            sql += " AND memory_tier = ?"
            params.append(self._tier_value(memory_tier))

        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(str(session_id))

        if not include_expired:
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(datetime.utcnow().isoformat())

        with self._get_connection() as conn:

            rows = conn.execute(
                sql,
                tuple(params)
            ).fetchall()

        result = [self._row_to_memory(row) for row in rows]

        for memory in result:
            memory.score = calculate_score(memory)

        result.sort(
            key=lambda item: item.score,
            reverse=True
        )

        return result
    

    async def find_duplicate(
        self,
        user_id,
        novel_id,
        memory_type,
        content
    ):
    
        with self._get_connection() as conn:
        
            row = conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    novel_id,
                    memory_type,
                    content,
                    importance,
                    hit_count,
                    score,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    metadata
    
                FROM memories
    
                WHERE user_id=?
                  AND novel_id=?
                  AND memory_type=?
                  AND content=?
    
                LIMIT 1
                """,
                (
                    user_id,
                    novel_id,
                    memory_type,
                    content
                )
            ).fetchone()
    
        if row is None:
            return None
    
        metadata = {}
    
        if row[11]:
        
            try:
                metadata = json.loads(row[11])
    
            except Exception:
                metadata = {}
    
        return MemoryItem(
        
            id=row[0],
    
            user_id=row[1],
    
            novel_id=row[2],
    
            memory_type=row[3],
    
            content=row[4],
    
            importance=row[5],

            hit_count=row[6],

            score=row[7],

            created_at=datetime.fromisoformat(row[8]),

            updated_at=datetime.fromisoformat(row[9])
                if row[9] else None,

            last_accessed_at=datetime.fromisoformat(row[10])
                if row[10] else None,

   
            metadata=metadata
        )

    async def find_duplicate_scoped(
        self,
        user_id: str,
        novel_id: str,
        memory_type: Any,
        content: str,
        memory_tier: Any,
        session_id: str | None,
    ) -> MemoryItem | None:

        memory_type_value = (
            memory_type.value
            if hasattr(memory_type, "value")
            else str(memory_type)
        )
        tier = self._tier_value(memory_tier)

        sql = """
            SELECT
                id,
                user_id,
                novel_id,
                memory_type,
                content,
                importance,
                hit_count,
                score,
                created_at,
                updated_at,
                last_accessed_at,
                metadata,
                memory_tier,
                session_id,
                expires_at,
                revision
            FROM memories
            WHERE user_id = ?
              AND novel_id = ?
              AND memory_type = ?
              AND content = ?
              AND memory_tier = ?
        """
        params: list[Any] = [
            user_id,
            novel_id,
            memory_type_value,
            content,
            tier,
        ]

        if tier == MemoryTier.SESSION.value:
            sql += " AND session_id = ?"
            params.append(session_id)

        sql += " LIMIT 1"

        with self._get_connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()

        if row is None:
            return None

        return self._row_to_memory(row)



    async def increment_hit_count(
        self,
        memory_id: str
    ):

        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:

            conn.execute(
                """
                UPDATE memories

                SET

                    hit_count = hit_count + 1,

                    last_accessed_at = ?

                WHERE id = ?
                """,
                (
                    now,
                    memory_id
                )
            )

            conn.commit()

    async def update_access_time(
        self,
        memory_id: str
    ):

        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:

            conn.execute(
                """
                UPDATE memories

                SET

                    last_accessed_at = ?

                WHERE id = ?
                """,
                (
                    now,
                    memory_id
                )
            )

            conn.commit()


    async def get(
        self,
        memory_id: str
    ):

        with self._get_connection() as conn:

            row = conn.execute(
                """
                SELECT

                    id,
                    user_id,
                    novel_id,
                    memory_type,
                    content,
                    importance,
                    hit_count,
                    score,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    metadata,
                    memory_tier,
                    session_id,
                    expires_at,
                    revision
                FROM memories
                WHERE id=?
                LIMIT 1
                """,
                (
                    memory_id,
                )
            ).fetchone()

        if row is None:
            return None

        return self._row_to_memory(row)
    async def search(
        self,
        user_id: str,
        novel_id: str,
        keyword: str,
        limit: int = 10
    ):

        sql = """
        SELECT

            id,
            user_id,
            novel_id,
            memory_type,
            content,
            importance,
            hit_count,
            score,
            created_at,
            updated_at,
            last_accessed_at,
            metadata,
            memory_tier,
            session_id,
            expires_at,
            revision

        FROM memories

        WHERE user_id=?
          AND novel_id=?
          AND content LIKE ?
          AND memory_tier IN ('working', 'long_term')
          AND (expires_at IS NULL OR expires_at > ?)

        ORDER BY score DESC

        LIMIT ?
        """

        with self._get_connection() as conn:

            rows = conn.execute(

                sql,

                (

                    user_id,
                    novel_id,
                    f"%{keyword}%",
                    datetime.utcnow().isoformat(),
                    limit

                )

            ).fetchall()

        result = [self._row_to_memory(row) for row in rows]

        for memory in result:
            memory.score = calculate_score(memory)

        result.sort(
            key=lambda x: x.score,
            reverse=True
        )

        return result

    async def list_lifecycle_events(
        self,
        memory_id: str,
    ) -> list[MemoryLifecycleEvent]:

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    event_id,
                    memory_id,
                    user_id,
                    novel_id,
                    event_type,
                    from_tier,
                    to_tier,
                    reason,
                    payload,
                    created_at
                FROM memory_lifecycle_events
                WHERE memory_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (memory_id,),
            ).fetchall()

        return [self._row_to_event(row) for row in rows]

    async def promote(
        self,
        memory_id: str,
        *,
        expected_revision: int,
        target_tier: str,
        basis: str,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[MemoryItem, MemoryLifecycleEvent]:

        transition_at = now or datetime.utcnow()
        target = MemoryTier(target_tier)

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    novel_id,
                    memory_type,
                    content,
                    importance,
                    hit_count,
                    score,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    metadata,
                    memory_tier,
                    session_id,
                    expires_at,
                    revision
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()

            if row is None:
                raise MemoryNotFoundError(
                    f"Memory not found: {memory_id}"
                )

            memory = self._row_to_memory(row)
            source = MemoryTier(memory.memory_tier)

            if memory.revision != expected_revision:
                raise MemoryLifecycleConflictError(
                    "Memory revision conflict: "
                    f"expected {expected_revision}, "
                    f"current {memory.revision}."
                )

            transitions = {
                MemoryTier.SESSION: MemoryTier.WORKING,
                MemoryTier.WORKING: MemoryTier.LONG_TERM,
            }
            if transitions.get(source) != target:
                raise MemoryLifecycleConflictError(
                    "Memory promotion must follow "
                    "session -> working -> long_term."
                )

            if source == MemoryTier.SESSION:
                if basis == "frequency":
                    eligible = memory.hit_count >= 2
                elif basis == "user_confirmed":
                    eligible = memory.importance >= 0.5
                else:
                    eligible = False

                if not eligible:
                    raise MemoryLifecycleConflictError(
                        "Session memory requires hit_count >= 2 "
                        "for frequency promotion or importance >= 0.5 "
                        "for user-confirmed promotion."
                    )

            if source == MemoryTier.WORKING:
                authoritative = {
                    "user_confirmed",
                    "accepted_manuscript",
                    "story_bible",
                }
                if (
                    basis not in authoritative
                    or memory.importance < 0.7
                ):
                    raise MemoryLifecycleConflictError(
                        "Working memory requires an authoritative "
                        "promotion basis and importance >= 0.7."
                    )

                if (
                    basis in {
                        "accepted_manuscript",
                        "story_bible",
                    }
                    and not memory.metadata.get("source_reference")
                ):
                    raise MemoryLifecycleConflictError(
                        "Authoritative source promotion requires "
                        "metadata.source_reference."
                    )

            memory.memory_tier = target
            memory.session_id = None
            memory.expires_at = (
                transition_at + timedelta(days=30)
                if target == MemoryTier.WORKING
                else None
            )
            memory.updated_at = transition_at
            memory.revision += 1

            conn.execute(
                """
                UPDATE memories
                SET memory_tier = ?,
                    session_id = NULL,
                    expires_at = ?,
                    updated_at = ?,
                    revision = ?
                WHERE id = ?
                """,
                (
                    target.value,
                    memory.expires_at.isoformat()
                    if memory.expires_at
                    else None,
                    transition_at.isoformat(),
                    memory.revision,
                    memory.id,
                ),
            )

            event = self._append_lifecycle_event(
                conn,
                memory=memory,
                event_type="memory_promoted",
                from_tier=source.value,
                to_tier=target.value,
                reason=reason,
                payload={
                    "basis": basis,
                    "revision": memory.revision,
                },
                created_at=transition_at,
            )
            conn.commit()

        return memory, event

    async def sweep_expired(
        self,
        *,
        user_id: str,
        novel_id: str,
        session_id: str | None = None,
        now: datetime | None = None,
        dry_run: bool = False,
    ) -> list[MemoryItem]:

        sweep_at = now or datetime.utcnow()
        sql = """
            SELECT
                id,
                user_id,
                novel_id,
                memory_type,
                content,
                importance,
                hit_count,
                score,
                created_at,
                updated_at,
                last_accessed_at,
                metadata,
                memory_tier,
                session_id,
                expires_at,
                revision
            FROM memories
            WHERE user_id = ?
              AND novel_id = ?
              AND memory_tier IN ('session', 'working')
              AND expires_at IS NOT NULL
              AND expires_at <= ?
        """
        params: list[Any] = [
            user_id,
            novel_id,
            sweep_at.isoformat(),
        ]
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)

        with self._get_connection() as conn:
            if not dry_run:
                conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(sql, tuple(params)).fetchall()
            memories = [self._row_to_memory(row) for row in rows]

            if not dry_run:
                for memory in memories:
                    conn.execute(
                        "DELETE FROM memories WHERE id = ?",
                        (memory.id,),
                    )
                    self._append_lifecycle_event(
                        conn,
                        memory=memory,
                        event_type="memory_evicted",
                        from_tier=self._tier_value(
                            memory.memory_tier
                        ),
                        to_tier=None,
                        reason="Memory TTL expired.",
                        payload={
                            "expires_at": (
                                memory.expires_at.isoformat()
                                if memory.expires_at
                                else None
                            ),
                        },
                        created_at=sweep_at,
                    )
                conn.commit()

        return memories

    async def evict_session(
        self,
        *,
        user_id: str,
        novel_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> list[MemoryItem]:

        closed_at = now or datetime.utcnow()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    novel_id,
                    memory_type,
                    content,
                    importance,
                    hit_count,
                    score,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    metadata,
                    memory_tier,
                    session_id,
                    expires_at,
                    revision
                FROM memories
                WHERE user_id = ?
                  AND novel_id = ?
                  AND memory_tier = 'session'
                  AND session_id = ?
                """,
                (user_id, novel_id, session_id),
            ).fetchall()
            memories = [self._row_to_memory(row) for row in rows]

            for memory in memories:
                conn.execute(
                    "DELETE FROM memories WHERE id = ?",
                    (memory.id,),
                )
                self._append_lifecycle_event(
                    conn,
                    memory=memory,
                    event_type="memory_evicted",
                    from_tier=MemoryTier.SESSION.value,
                    to_tier=None,
                    reason="Session closed.",
                    payload={"session_id": session_id},
                    created_at=closed_at,
                )
            conn.commit()

        return memories
