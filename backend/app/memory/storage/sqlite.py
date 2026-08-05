import json
import sqlite3
import uuid

from datetime import datetime
from pathlib import Path

from ..schemas import MemoryItem
from ..score import calculate_score
from .base import BaseMemoryStorage


class SQLiteMemoryStorage(BaseMemoryStorage):

    def __init__(
        self,
        db_path: str = "/app/data/memory.db"
    ):

        self.db_path = db_path

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

                    metadata TEXT

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
                    "ALTER TABLE memories ADD COLUMN last_accessed_at TEXT"

            }

            for column, sql in upgrades.items():

                if column not in columns:

                    print(f"[DB Upgrade] add column -> {column}")

                    conn.execute(sql)

            conn.commit()

    async def save(
        self,
        memory: MemoryItem
    ):

        if memory.id is None:

            memory.id = str(
                uuid.uuid4()
            )

        now = datetime.utcnow()

        if memory.created_at is None:
            memory.created_at = now

        if memory.updated_at is None:
            memory.updated_at = now

        if memory.last_accessed_at is None:
            memory.last_accessed_at = now

        memory.score = calculate_score(memory)

        if memory.hit_count is None:
            memory.hit_count = 0


        metadata = json.dumps(
            memory.metadata or {},
            ensure_ascii=False
        )

        with self._get_connection() as conn:

            conn.execute(
                """
                INSERT OR REPLACE INTO memories(

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

                )

                VALUES(

                    ?,?,?,?,?,?,?,
                    ?,?,?,?,?

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
                    metadata

                )

            )

            conn.commit()

        return memory

    async def delete(
        self,
        memory_id: str
    ):

        with self._get_connection() as conn:

            cursor = conn.execute(
                """
                DELETE FROM memories
                WHERE id=?
                """,
                (memory_id,)
            )

            conn.commit()

        if cursor.rowcount == 0:
            return None

        return {
            "id": memory_id
        }

    async def update(
        self,
        memory: MemoryItem
    ):

        if memory.updated_at is None:
            memory.updated_at = datetime.utcnow()

        if memory.last_accessed_at is None:
            memory.last_accessed_at = datetime.utcnow()
        memory.score = calculate_score(memory)


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
                    metadata=?

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
                    memory.id

                )

            )

            conn.commit()

        return memory
    
    async def query(
        self,
        user_id: str,
        novel_id: str,
        memory_type=None
    ):

        if memory_type is not None:

            memory_type_value = (
                memory_type.value
                if hasattr(memory_type, "value")
                else str(memory_type)
            )

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
                    metadata
                FROM memories
                WHERE user_id = ?
                  AND novel_id = ?
                  AND memory_type = ?
            """

            params = (
                user_id,
                novel_id,
                memory_type_value
            )

        else:

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
                    metadata
                FROM memories
                WHERE user_id = ?
                  AND novel_id = ?
            """

            params = (
                user_id,
                novel_id
            )

        with self._get_connection() as conn:

            rows = conn.execute(
                sql,
                params
            ).fetchall()

        result = []

        for row in rows:

            metadata = {}

            if row["metadata"]:

                try:
                    metadata = json.loads(
                        row["metadata"]
                    )

                except (json.JSONDecodeError, TypeError):
                    metadata = {}

            memory = MemoryItem(

                id=row["id"],

                user_id=row["user_id"],

                novel_id=row["novel_id"],

                memory_type=row["memory_type"],

                content=row["content"],

                importance=row["importance"],

                hit_count=(
                    row["hit_count"]
                    if row["hit_count"] is not None
                    else 1
                ),

                score=(
                    row["score"]
                    if row["score"] is not None
                    else 0.0
                ),

                created_at=(
                    datetime.fromisoformat(
                        row["created_at"]
                    )
                    if row["created_at"]
                    else None
                ),

                updated_at=(
                    datetime.fromisoformat(
                        row["updated_at"]
                    )
                    if row["updated_at"]
                    else None
                ),

                last_accessed_at=(
                    datetime.fromisoformat(
                        row["last_accessed_at"]
                    )
                    if row["last_accessed_at"]
                    else None
                ),

                metadata=metadata

            )

            # 查询时动态计算最新分数
            memory.score = calculate_score(memory)

            result.append(memory)

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
                    metadata

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

        import json

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

            memory_type=MemoryType(row[3]),

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
            metadata

        FROM memories

        WHERE user_id=?
          AND novel_id=?
          AND content LIKE ?

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
                    limit

                )

            ).fetchall()

        result = []

        for row in rows:

            metadata = {}

            if row["metadata"]:

                try:

                    metadata = json.loads(
                        row["metadata"]
                    )

                except Exception:

                    metadata = {}

            memory = MemoryItem(

                id=row["id"],

                user_id=row["user_id"],

                novel_id=row["novel_id"],

                memory_type=row["memory_type"],

                content=row["content"],

                importance=row["importance"],

                hit_count=row["hit_count"],

                score=row["score"],

                created_at=datetime.fromisoformat(
                    row["created_at"]
                ),

                updated_at=datetime.fromisoformat(
                    row["updated_at"]
                ) if row["updated_at"] else None,

                last_accessed_at=datetime.fromisoformat(
                    row["last_accessed_at"]
                ) if row["last_accessed_at"] else None,

                metadata=metadata

            )

            memory.score = calculate_score(memory)

            result.append(memory)

        result.sort(
            key=lambda x: x.score,
            reverse=True
        )

        return result   
