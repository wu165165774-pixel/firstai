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
    NovelProject,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryBible,
    StoryBibleRevision,
    StoryBibleUpdate,
)


class NovelProjectNotFoundError(KeyError):
    pass


class NovelRevisionConflictError(RuntimeError):
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


class NovelProjectStorage:

    def __init__(
        self,
        db_path: str | None = None,
    ) -> None:
        self.db_path = db_path or os.getenv(
            "NOVELFORGE_NOVEL_DB_PATH",
            "/app/data/novels.db",
        )
        Path(self.db_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
        )
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
                CREATE TABLE IF NOT EXISTS novel_projects (
                    novel_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    genre TEXT NOT NULL DEFAULT '',
                    premise TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT 'zh-CN',
                    target_word_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'planning',
                    style_guide_json TEXT NOT NULL DEFAULT '{}',
                    constraints_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_novel_projects_user
                ON novel_projects(user_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_novel_projects_status
                ON novel_projects(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS story_bibles (
                    novel_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 1,
                    world_json TEXT NOT NULL DEFAULT '{}',
                    characters_json TEXT NOT NULL DEFAULT '[]',
                    factions_json TEXT NOT NULL DEFAULT '[]',
                    locations_json TEXT NOT NULL DEFAULT '[]',
                    rules_json TEXT NOT NULL DEFAULT '[]',
                    themes_json TEXT NOT NULL DEFAULT '[]',
                    timeline_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS story_bible_revisions (
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(novel_id, revision),
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_story_bible_revisions_time
                ON story_bible_revisions(novel_id, revision DESC);
                """
            )
            conn.commit()

    def create_project(
        self,
        payload: NovelProjectCreate,
    ) -> NovelProject:
        novel_id = str(uuid.uuid4())
        now = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO novel_projects (
                    novel_id,
                    user_id,
                    title,
                    genre,
                    premise,
                    language,
                    target_word_count,
                    status,
                    style_guide_json,
                    constraints_json,
                    metadata_json,
                    revision,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    novel_id,
                    payload.user_id,
                    payload.title,
                    payload.genre,
                    payload.premise,
                    payload.language,
                    payload.target_word_count,
                    payload.status,
                    _json_dump(payload.style_guide),
                    _json_dump(payload.constraints),
                    _json_dump(payload.metadata),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO story_bibles (
                    novel_id,
                    revision,
                    updated_at
                ) VALUES (?, 1, ?)
                """,
                (novel_id, now),
            )
            bible = self._story_bible_from_row(
                conn.execute(
                    "SELECT * FROM story_bibles WHERE novel_id = ?",
                    (novel_id,),
                ).fetchone()
            )
            self._insert_story_bible_revision(
                conn,
                bible,
                now,
            )
            conn.commit()

        return self.get_project(novel_id)

    def get_project(
        self,
        novel_id: str,
    ) -> NovelProject:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.*,
                       b.revision AS story_bible_revision
                FROM novel_projects AS p
                JOIN story_bibles AS b
                  ON b.novel_id = p.novel_id
                WHERE p.novel_id = ?
                """,
                (novel_id,),
            ).fetchone()

        if row is None:
            raise NovelProjectNotFoundError(novel_id)
        return self._project_from_row(row)

    def list_projects(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NovelProject]:
        normalized_limit = min(max(int(limit), 1), 500)
        normalized_offset = max(int(offset), 0)
        clauses: list[str] = []
        params: list[Any] = []

        if user_id:
            clauses.append("p.user_id = ?")
            params.append(user_id)
        if status:
            clauses.append("p.status = ?")
            params.append(status)

        where = (
            " WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )
        params.extend([
            normalized_limit,
            normalized_offset,
        ])

        sql = f"""
            SELECT p.*,
                   b.revision AS story_bible_revision
            FROM novel_projects AS p
            JOIN story_bibles AS b
              ON b.novel_id = p.novel_id
            {where}
            ORDER BY p.updated_at DESC, p.novel_id ASC
            LIMIT ? OFFSET ?
        """

        with self._connect() as conn:
            rows = conn.execute(
                sql,
                tuple(params),
            ).fetchall()

        return [
            self._project_from_row(row)
            for row in rows
        ]

    def update_project(
        self,
        novel_id: str,
        payload: NovelProjectUpdate,
    ) -> NovelProject:
        updates = payload.model_dump(
            exclude_unset=True,
        )
        expected_revision = updates.pop(
            "expected_revision",
            None,
        )

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM novel_projects WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()

            if row is None:
                raise NovelProjectNotFoundError(novel_id)

            current_revision = int(row["revision"])
            if (
                expected_revision is not None
                and expected_revision != current_revision
            ):
                raise NovelRevisionConflictError(
                    f"Novel project revision conflict: "
                    f"expected={expected_revision}, "
                    f"actual={current_revision}"
                )

            if not updates:
                conn.commit()
                return self.get_project(novel_id)

            column_map = {
                "title": "title",
                "genre": "genre",
                "premise": "premise",
                "language": "language",
                "target_word_count": "target_word_count",
                "status": "status",
                "style_guide": "style_guide_json",
                "constraints": "constraints_json",
                "metadata": "metadata_json",
            }
            assignments: list[str] = []
            values: list[Any] = []

            for field, value in updates.items():
                column = column_map[field]
                assignments.append(f"{column} = ?")
                if field in {
                    "style_guide",
                    "constraints",
                    "metadata",
                }:
                    value = _json_dump(value)
                values.append(value)

            now = _utc_now()
            assignments.extend([
                "revision = revision + 1",
                "updated_at = ?",
            ])
            values.extend([now, novel_id])

            conn.execute(
                f"""
                UPDATE novel_projects
                SET {', '.join(assignments)}
                WHERE novel_id = ?
                """,
                tuple(values),
            )
            conn.commit()

        return self.get_project(novel_id)

    def get_story_bible(
        self,
        novel_id: str,
    ) -> StoryBible:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM story_bibles WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise RuntimeError(
                f"Story Bible is missing for novel {novel_id}"
            )
        return self._story_bible_from_row(row)

    def update_story_bible(
        self,
        novel_id: str,
        payload: StoryBibleUpdate,
    ) -> StoryBible:
        updates = payload.model_dump(
            exclude_unset=True,
        )
        expected_revision = updates.pop(
            "expected_revision",
            None,
        )

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM story_bibles WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()

            if row is None:
                project = conn.execute(
                    "SELECT novel_id FROM novel_projects WHERE novel_id = ?",
                    (novel_id,),
                ).fetchone()
                if project is None:
                    raise NovelProjectNotFoundError(novel_id)
                raise RuntimeError(
                    f"Story Bible is missing for novel {novel_id}"
                )

            current_revision = int(row["revision"])
            if (
                expected_revision is not None
                and expected_revision != current_revision
            ):
                raise NovelRevisionConflictError(
                    f"Story Bible revision conflict: "
                    f"expected={expected_revision}, "
                    f"actual={current_revision}"
                )

            if not updates:
                conn.commit()
                return self._story_bible_from_row(row)

            column_map = {
                "world": "world_json",
                "characters": "characters_json",
                "factions": "factions_json",
                "locations": "locations_json",
                "rules": "rules_json",
                "themes": "themes_json",
                "timeline": "timeline_json",
                "metadata": "metadata_json",
            }
            assignments: list[str] = []
            values: list[Any] = []

            for field, value in updates.items():
                assignments.append(
                    f"{column_map[field]} = ?"
                )
                values.append(_json_dump(value))

            now = _utc_now()
            assignments.extend([
                "revision = revision + 1",
                "updated_at = ?",
            ])
            values.extend([now, novel_id])

            conn.execute(
                f"""
                UPDATE story_bibles
                SET {', '.join(assignments)}
                WHERE novel_id = ?
                """,
                tuple(values),
            )
            updated_row = conn.execute(
                "SELECT * FROM story_bibles WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()
            bible = self._story_bible_from_row(updated_row)
            self._insert_story_bible_revision(
                conn,
                bible,
                now,
            )
            conn.execute(
                """
                UPDATE novel_projects
                SET updated_at = ?
                WHERE novel_id = ?
                """,
                (now, novel_id),
            )
            conn.commit()

        return bible

    def list_story_bible_revisions(
        self,
        novel_id: str,
        *,
        limit: int = 100,
    ) -> list[StoryBibleRevision]:
        if not self._project_exists(novel_id):
            raise NovelProjectNotFoundError(novel_id)

        normalized_limit = min(max(int(limit), 1), 500)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT novel_id,
                       revision,
                       snapshot_json,
                       created_at
                FROM story_bible_revisions
                WHERE novel_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (novel_id, normalized_limit),
            ).fetchall()

        return [
            self._revision_from_row(row)
            for row in rows
        ]

    def get_story_bible_revision(
        self,
        novel_id: str,
        revision: int,
    ) -> StoryBibleRevision:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT novel_id,
                       revision,
                       snapshot_json,
                       created_at
                FROM story_bible_revisions
                WHERE novel_id = ?
                  AND revision = ?
                """,
                (novel_id, int(revision)),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise NovelProjectNotFoundError(
                f"{novel_id}:story-bible:{revision}"
            )
        return self._revision_from_row(row)

    def _project_exists(self, novel_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM novel_projects WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()
        return row is not None

    def _insert_story_bible_revision(
        self,
        conn: sqlite3.Connection,
        bible: StoryBible,
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO story_bible_revisions (
                novel_id,
                revision,
                snapshot_json,
                created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                bible.novel_id,
                bible.revision,
                _json_dump(bible.model_dump()),
                created_at,
            ),
        )

    @staticmethod
    def _project_from_row(
        row: sqlite3.Row,
    ) -> NovelProject:
        return NovelProject(
            novel_id=row["novel_id"],
            user_id=row["user_id"],
            title=row["title"],
            genre=row["genre"],
            premise=row["premise"],
            language=row["language"],
            target_word_count=int(
                row["target_word_count"]
            ),
            status=row["status"],
            style_guide=_json_load(
                row["style_guide_json"],
                {},
            ),
            constraints=_json_load(
                row["constraints_json"],
                [],
            ),
            metadata=_json_load(
                row["metadata_json"],
                {},
            ),
            revision=int(row["revision"]),
            story_bible_revision=int(
                row["story_bible_revision"]
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _story_bible_from_row(
        row: sqlite3.Row,
    ) -> StoryBible:
        return StoryBible(
            novel_id=row["novel_id"],
            revision=int(row["revision"]),
            world=_json_load(row["world_json"], {}),
            characters=_json_load(
                row["characters_json"],
                [],
            ),
            factions=_json_load(
                row["factions_json"],
                [],
            ),
            locations=_json_load(
                row["locations_json"],
                [],
            ),
            rules=_json_load(row["rules_json"], []),
            themes=_json_load(
                row["themes_json"],
                [],
            ),
            timeline=_json_load(
                row["timeline_json"],
                [],
            ),
            metadata=_json_load(
                row["metadata_json"],
                {},
            ),
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _revision_from_row(
        row: sqlite3.Row,
    ) -> StoryBibleRevision:
        snapshot = StoryBible.model_validate(
            json.loads(row["snapshot_json"])
        )
        return StoryBibleRevision(
            novel_id=row["novel_id"],
            revision=int(row["revision"]),
            snapshot=snapshot,
            created_at=row["created_at"],
        )
