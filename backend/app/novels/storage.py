from __future__ import annotations

import json
import os
import sqlite3
import uuid

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schemas import (
    ChapterPlan,
    ChapterPlanCreate,
    ChapterPlanRevision,
    ChapterPlanUpdate,
    EntityResolution,
    EntityResolveRequest,
    NovelPlan,
    NovelPlanRevision,
    NovelPlanUpdate,
    NovelEntity,
    NovelEntityCreate,
    NovelEntityUpdate,
    NovelProject,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryArc,
    StoryArcCreate,
    StoryArcRevision,
    StoryArcUpdate,
    StoryBible,
    StoryBibleEntityAlignRequest,
    StoryBibleEntityAlignment,
    StoryBibleEntityBinding,
    StoryBibleRevision,
    StoryBibleUpdate,
    clean_entity_name,
    normalize_entity_name,
)


class NovelProjectNotFoundError(KeyError):
    pass


class NovelRevisionConflictError(RuntimeError):
    pass


class NovelEntityReferenceError(NovelRevisionConflictError):
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


_ENTITY_ID_PREFIXES = {
    "character": "char",
    "organization": "org",
    "location": "loc",
    "item": "item",
    "creature": "creature",
    "concept": "concept",
}


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

    @staticmethod
    def _assert_expected_source_revisions(
        row: sqlite3.Row,
        expectations: dict[str, int | None],
        *,
        entity_name: str,
    ) -> None:
        for column, expected in expectations.items():
            if expected is None:
                continue

            actual = int(row[column])
            if expected != actual:
                source_name = column.removesuffix("_revision")
                raise NovelRevisionConflictError(
                    f"{entity_name} source revision conflict: "
                    f"source={source_name}, expected={expected}, "
                    f"actual={actual}"
                )

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

                CREATE TABLE IF NOT EXISTS novel_entities (
                    novel_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    canonical_name_normalized TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    description TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(novel_id, entity_id),
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_novel_entities_type
                ON novel_entities(
                    novel_id,
                    entity_type,
                    canonical_name_normalized,
                    entity_id
                );

                CREATE TABLE IF NOT EXISTS novel_entity_aliases (
                    novel_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    alias_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(
                        novel_id,
                        entity_id,
                        normalized_alias
                    ),
                    FOREIGN KEY(novel_id, entity_id)
                        REFERENCES novel_entities(novel_id, entity_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_entity_alias_resolution
                ON novel_entity_aliases(
                    novel_id,
                    normalized_alias,
                    alias_kind,
                    entity_id
                );

                CREATE TABLE IF NOT EXISTS novel_plans (
                    novel_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 1,
                    source_project_revision INTEGER NOT NULL,
                    source_story_bible_revision INTEGER NOT NULL,
                    story_premise TEXT NOT NULL DEFAULT '',
                    core_conflict TEXT NOT NULL DEFAULT '',
                    central_question TEXT NOT NULL DEFAULT '',
                    ending_direction TEXT NOT NULL DEFAULT '',
                    themes_json TEXT NOT NULL DEFAULT '[]',
                    main_plot_json TEXT NOT NULL DEFAULT '[]',
                    character_arcs_json TEXT NOT NULL DEFAULT '[]',
                    volume_plans_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS novel_plan_revisions (
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(novel_id, revision),
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_novel_plan_revisions_time
                ON novel_plan_revisions(novel_id, revision DESC);

                CREATE TABLE IF NOT EXISTS story_arcs (
                    arc_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    volume_number INTEGER NOT NULL,
                    arc_number INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    source_project_revision INTEGER NOT NULL,
                    source_story_bible_revision INTEGER NOT NULL,
                    source_novel_plan_revision INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    opening_state TEXT NOT NULL DEFAULT '',
                    closing_state TEXT NOT NULL DEFAULT '',
                    core_conflict TEXT NOT NULL DEFAULT '',
                    stakes TEXT NOT NULL DEFAULT '',
                    turning_points_json TEXT NOT NULL DEFAULT '[]',
                    character_progression_json TEXT NOT NULL DEFAULT '[]',
                    plot_threads_json TEXT NOT NULL DEFAULT '[]',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    target_chapter_start INTEGER,
                    target_chapter_end INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE,
                    UNIQUE(novel_id, volume_number, arc_number)
                );

                CREATE INDEX IF NOT EXISTS idx_story_arcs_order
                ON story_arcs(
                    novel_id,
                    volume_number,
                    arc_number
                );

                CREATE INDEX IF NOT EXISTS idx_story_arcs_volume
                ON story_arcs(
                    novel_id,
                    volume_number,
                    updated_at DESC
                );

                CREATE TABLE IF NOT EXISTS story_arc_revisions (
                    arc_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(arc_id, revision),
                    FOREIGN KEY(arc_id)
                        REFERENCES story_arcs(arc_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_story_arc_revisions_time
                ON story_arc_revisions(
                    arc_id,
                    revision DESC
                );


                CREATE TABLE IF NOT EXISTS chapter_plans (
                    chapter_plan_id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    arc_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    source_project_revision INTEGER NOT NULL,
                    source_story_bible_revision INTEGER NOT NULL,
                    source_novel_plan_revision INTEGER NOT NULL,
                    source_story_arc_revision INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    pov_character_id TEXT,
                    pov_character_name TEXT NOT NULL DEFAULT '',
                    opening_state TEXT NOT NULL DEFAULT '',
                    closing_state TEXT NOT NULL DEFAULT '',
                    conflict TEXT NOT NULL DEFAULT '',
                    reveal TEXT NOT NULL DEFAULT '',
                    hook TEXT NOT NULL DEFAULT '',
                    scene_beats_json TEXT NOT NULL DEFAULT '[]',
                    continuity_dependencies_json TEXT NOT NULL DEFAULT '[]',
                    target_word_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(arc_id)
                        REFERENCES story_arcs(arc_id)
                        ON DELETE CASCADE,
                    UNIQUE(novel_id, chapter_number)
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_plans_order
                ON chapter_plans(
                    novel_id,
                    chapter_number
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_plans_arc
                ON chapter_plans(
                    novel_id,
                    arc_id,
                    chapter_number
                );

                CREATE TABLE IF NOT EXISTS chapter_plan_revisions (
                    chapter_plan_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(chapter_plan_id, revision),
                    FOREIGN KEY(chapter_plan_id)
                        REFERENCES chapter_plans(chapter_plan_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(novel_id)
                        REFERENCES novel_projects(novel_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_plan_revisions_time
                ON chapter_plan_revisions(
                    chapter_plan_id,
                    revision DESC
                );
                """
            )
            self._backfill_novel_plans(conn)
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
            conn.execute(
                """
                INSERT INTO novel_plans (
                    novel_id,
                    revision,
                    source_project_revision,
                    source_story_bible_revision,
                    story_premise,
                    created_at,
                    updated_at
                ) VALUES (?, 1, 1, 1, ?, ?, ?)
                """,
                (
                    novel_id,
                    payload.premise,
                    now,
                    now,
                ),
            )
            plan_row = conn.execute(
                """
                SELECT pl.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision
                FROM novel_plans AS pl
                JOIN novel_projects AS p
                  ON p.novel_id = pl.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = pl.novel_id
                WHERE pl.novel_id = ?
                """,
                (novel_id,),
            ).fetchone()
            self._insert_novel_plan_revision(
                conn,
                self._novel_plan_from_row(plan_row),
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

    def _advance_canon_revision(
        self,
        conn: sqlite3.Connection,
        novel_id: str,
        now: str,
        *,
        characters: list[dict[str, Any]] | None = None,
    ) -> StoryBible:
        if characters is None:
            conn.execute(
                """
                UPDATE story_bibles
                SET revision = revision + 1,
                    updated_at = ?
                WHERE novel_id = ?
                """,
                (now, novel_id),
            )
        else:
            conn.execute(
                """
                UPDATE story_bibles
                SET characters_json = ?,
                    revision = revision + 1,
                    updated_at = ?
                WHERE novel_id = ?
                """,
                (_json_dump(characters), now, novel_id),
            )

        row = conn.execute(
            "SELECT * FROM story_bibles WHERE novel_id = ?",
            (novel_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"Story Bible is missing for novel {novel_id}"
            )

        bible = self._story_bible_from_row(row)
        self._insert_story_bible_revision(conn, bible, now)
        conn.execute(
            """
            UPDATE novel_projects
            SET updated_at = ?
            WHERE novel_id = ?
            """,
            (now, novel_id),
        )
        return bible

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

    @staticmethod
    def _story_bible_character_value(
        character: dict[str, Any],
        *keys: str,
    ) -> str:
        for key in keys:
            value = clean_entity_name(character.get(key))
            if value:
                return value
        return ""

    def align_story_bible_entities(
        self,
        novel_id: str,
        payload: StoryBibleEntityAlignRequest,
    ) -> StoryBibleEntityAlignment:
        now = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            bible_row = conn.execute(
                "SELECT * FROM story_bibles WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()
            if bible_row is None:
                if not self._project_exists(novel_id):
                    raise NovelProjectNotFoundError(novel_id)
                raise RuntimeError(
                    f"Story Bible is missing for novel {novel_id}"
                )

            current_revision = int(bible_row["revision"])
            if payload.expected_revision != current_revision:
                raise NovelRevisionConflictError(
                    "Story Bible revision conflict: "
                    f"expected={payload.expected_revision}, "
                    f"actual={current_revision}"
                )

            characters = _json_load(
                bible_row["characters_json"],
                [],
            )
            aligned_characters: list[dict[str, Any]] = []
            bindings: list[StoryBibleEntityBinding] = []
            created_entities: list[NovelEntity] = []
            bound_ids: set[str] = set()

            for index, raw_character in enumerate(characters):
                if not isinstance(raw_character, dict):
                    raise NovelEntityReferenceError(
                        "Story Bible character must be an object: "
                        f"index={index}"
                    )

                character = dict(raw_character)
                explicit_id = self._story_bible_character_value(
                    character,
                    "entity_id",
                    "character_id",
                    "id",
                )
                name = self._story_bible_character_value(
                    character,
                    "canonical_name",
                    "name",
                )

                entity: NovelEntity | None = None
                action = "existing_id"

                if explicit_id:
                    entity_row = conn.execute(
                        """
                        SELECT * FROM novel_entities
                        WHERE novel_id = ? AND entity_id = ?
                        """,
                        (novel_id, explicit_id),
                    ).fetchone()

                    if entity_row is not None:
                        entity = self._entity_from_row(entity_row)
                        if entity.entity_type != "character":
                            raise NovelEntityReferenceError(
                                "Story Bible character references a "
                                "non-character entity: "
                                f"index={index}, entity_id={explicit_id}, "
                                f"entity_type={entity.entity_type}"
                            )

                        if name:
                            _, name_rows = self._resolve_entity_rows(
                                conn,
                                novel_id,
                                name,
                                entity_type="character",
                            )
                            matched_ids = {
                                row["entity_id"]
                                for row in name_rows
                            }
                            if explicit_id not in matched_ids:
                                raise NovelEntityReferenceError(
                                    "Story Bible character ID/name conflict: "
                                    f"index={index}, entity_id={explicit_id}, "
                                    f"name={name}"
                                )
                    else:
                        if not name:
                            raise NovelEntityReferenceError(
                                "Cannot create a missing Story Bible "
                                "character entity without a name: "
                                f"index={index}, entity_id={explicit_id}"
                            )

                        _, name_rows = self._resolve_entity_rows(
                            conn,
                            novel_id,
                            name,
                            entity_type="character",
                        )
                        if name_rows:
                            matched_ids = {
                                row["entity_id"]
                                for row in name_rows
                            }
                            raise NovelEntityReferenceError(
                                "Story Bible character ID conflicts with "
                                "an existing name binding: "
                                f"index={index}, entity_id={explicit_id}, "
                                f"name={name}, matches={sorted(matched_ids)}"
                            )

                        if not payload.create_missing:
                            raise NovelEntityReferenceError(
                                "Story Bible character entity is missing: "
                                f"index={index}, entity_id={explicit_id}"
                            )

                        entity = self._create_story_bible_entity(
                            conn,
                            novel_id,
                            character,
                            index=index,
                            entity_id=explicit_id,
                            canonical_name=name,
                            now=now,
                        )
                        created_entities.append(entity)
                        action = "created"
                else:
                    if not name:
                        raise NovelEntityReferenceError(
                            "Story Bible character requires a name: "
                            f"index={index}"
                        )

                    _, name_rows = self._resolve_entity_rows(
                        conn,
                        novel_id,
                        name,
                        entity_type="character",
                    )
                    if len(name_rows) > 1:
                        candidate_ids = sorted(
                            row["entity_id"]
                            for row in name_rows
                        )
                        raise NovelEntityReferenceError(
                            "Story Bible character name is ambiguous: "
                            f"index={index}, name={name}, "
                            f"candidates={candidate_ids}"
                        )
                    if len(name_rows) == 1:
                        entity = self._entity_from_row(name_rows[0])
                        action = "resolved_name"
                    else:
                        if not payload.create_missing:
                            raise NovelEntityReferenceError(
                                "Story Bible character entity is missing: "
                                f"index={index}, name={name}"
                            )
                        entity = self._create_story_bible_entity(
                            conn,
                            novel_id,
                            character,
                            index=index,
                            entity_id=None,
                            canonical_name=name,
                            now=now,
                        )
                        created_entities.append(entity)
                        action = "created"

                assert entity is not None
                if entity.entity_id in bound_ids:
                    raise NovelEntityReferenceError(
                        "Story Bible character entity is bound more than once: "
                        f"entity_id={entity.entity_id}"
                    )
                bound_ids.add(entity.entity_id)

                character["entity_id"] = entity.entity_id
                aligned_characters.append(character)
                bindings.append(
                    StoryBibleEntityBinding(
                        character_index=index,
                        entity_id=entity.entity_id,
                        canonical_name=entity.canonical_name,
                        action=action,
                    )
                )

            characters_changed = aligned_characters != characters
            changed = characters_changed or bool(created_entities)
            if changed:
                bible = self._advance_canon_revision(
                    conn,
                    novel_id,
                    now,
                    characters=(
                        aligned_characters
                        if characters_changed
                        else None
                    ),
                )
            else:
                bible = self._story_bible_from_row(bible_row)

            conn.commit()

        return StoryBibleEntityAlignment(
            story_bible=bible,
            bindings=bindings,
            created_entities=created_entities,
            changed=changed,
        )

    def _create_story_bible_entity(
        self,
        conn: sqlite3.Connection,
        novel_id: str,
        character: dict[str, Any],
        *,
        index: int,
        entity_id: str | None,
        canonical_name: str,
        now: str,
    ) -> NovelEntity:
        raw_aliases = character.get("aliases", [])
        if raw_aliases is None:
            raw_aliases = []
        if not isinstance(raw_aliases, list):
            raise NovelEntityReferenceError(
                "Story Bible character aliases must be a list: "
                f"index={index}"
            )

        description = character.get("description")
        if not isinstance(description, str) or not description.strip():
            role = character.get("role")
            description = role if isinstance(role, str) else ""

        try:
            create = NovelEntityCreate(
                entity_id=entity_id,
                entity_type="character",
                canonical_name=canonical_name,
                aliases=raw_aliases,
                description=description[:8000],
                metadata={
                    "source": "story_bible",
                    "story_bible_character_index": index,
                },
            )
        except ValidationError as exc:
            raise NovelEntityReferenceError(
                "Invalid Story Bible character entity: "
                f"index={index}, error={exc.errors()}"
            ) from exc

        return self._insert_entity(
            conn,
            novel_id,
            create,
            now,
        )

    @staticmethod
    def _new_entity_id(entity_type: str) -> str:
        prefix = _ENTITY_ID_PREFIXES[entity_type]
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _entity_aliases(
        canonical_name: str,
        aliases: list[str],
    ) -> list[str]:
        canonical_normalized = normalize_entity_name(
            canonical_name
        )
        result: list[str] = []
        seen = {canonical_normalized}

        for alias in aliases:
            normalized = normalize_entity_name(alias)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(alias)

        return result

    @staticmethod
    def _replace_entity_aliases(
        conn: sqlite3.Connection,
        entity: NovelEntity,
        now: str,
    ) -> None:
        conn.execute(
            """
            DELETE FROM novel_entity_aliases
            WHERE novel_id = ? AND entity_id = ?
            """,
            (entity.novel_id, entity.entity_id),
        )

        indexed_names = [
            (
                entity.canonical_name,
                normalize_entity_name(entity.canonical_name),
                "canonical",
            ),
            *[
                (
                    alias,
                    normalize_entity_name(alias),
                    "alias",
                )
                for alias in entity.aliases
            ],
        ]

        conn.executemany(
            """
            INSERT INTO novel_entity_aliases (
                novel_id,
                entity_id,
                alias,
                normalized_alias,
                alias_kind,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    entity.novel_id,
                    entity.entity_id,
                    alias,
                    normalized,
                    kind,
                    now,
                )
                for alias, normalized, kind in indexed_names
            ],
        )

    def _insert_entity(
        self,
        conn: sqlite3.Connection,
        novel_id: str,
        payload: NovelEntityCreate,
        now: str,
    ) -> NovelEntity:
        entity_id = (
            payload.entity_id
            or self._new_entity_id(payload.entity_type)
        )
        aliases = self._entity_aliases(
            payload.canonical_name,
            payload.aliases,
        )

        try:
            conn.execute(
                """
                INSERT INTO novel_entities (
                    novel_id,
                    entity_id,
                    entity_type,
                    canonical_name,
                    canonical_name_normalized,
                    aliases_json,
                    description,
                    revision,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    novel_id,
                    entity_id,
                    payload.entity_type,
                    payload.canonical_name,
                    normalize_entity_name(payload.canonical_name),
                    _json_dump(aliases),
                    payload.description,
                    _json_dump(payload.metadata),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise NovelRevisionConflictError(
                "Entity ID conflict: "
                f"novel_id={novel_id}, entity_id={entity_id}"
            ) from exc

        row = conn.execute(
            """
            SELECT * FROM novel_entities
            WHERE novel_id = ? AND entity_id = ?
            """,
            (novel_id, entity_id),
        ).fetchone()
        entity = self._entity_from_row(row)
        self._replace_entity_aliases(conn, entity, now)
        return entity

    def create_entity(
        self,
        novel_id: str,
        payload: NovelEntityCreate,
    ) -> NovelEntity:
        now = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = conn.execute(
                "SELECT novel_id FROM novel_projects WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()
            if project is None:
                raise NovelProjectNotFoundError(novel_id)

            entity = self._insert_entity(
                conn,
                novel_id,
                payload,
                now,
            )
            self._advance_canon_revision(
                conn,
                novel_id,
                now,
            )
            conn.commit()

        return entity

    def list_entities(
        self,
        novel_id: str,
        *,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[NovelEntity]:
        if not self._project_exists(novel_id):
            raise NovelProjectNotFoundError(novel_id)

        where = ["novel_id = ?"]
        params: list[Any] = [novel_id]
        if entity_type is not None:
            where.append("entity_type = ?")
            params.append(entity_type)

        params.extend([
            min(max(int(limit), 1), 500),
            max(int(offset), 0),
        ])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM novel_entities
                WHERE {' AND '.join(where)}
                ORDER BY canonical_name_normalized, entity_id
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        return [self._entity_from_row(row) for row in rows]

    def get_entity(
        self,
        novel_id: str,
        entity_id: str,
    ) -> NovelEntity:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM novel_entities
                WHERE novel_id = ? AND entity_id = ?
                """,
                (novel_id, entity_id),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise NovelProjectNotFoundError(
                f"{novel_id}:entity:{entity_id}"
            )
        return self._entity_from_row(row)

    def update_entity(
        self,
        novel_id: str,
        entity_id: str,
        payload: NovelEntityUpdate,
    ) -> NovelEntity:
        updates = payload.model_dump(exclude_unset=True)
        expected_revision = updates.pop("expected_revision", None)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM novel_entities
                WHERE novel_id = ? AND entity_id = ?
                """,
                (novel_id, entity_id),
            ).fetchone()

            if row is None:
                project = conn.execute(
                    "SELECT novel_id FROM novel_projects WHERE novel_id = ?",
                    (novel_id,),
                ).fetchone()
                if project is None:
                    raise NovelProjectNotFoundError(novel_id)
                raise NovelProjectNotFoundError(
                    f"{novel_id}:entity:{entity_id}"
                )

            current_revision = int(row["revision"])
            if (
                expected_revision is not None
                and expected_revision != current_revision
            ):
                raise NovelRevisionConflictError(
                    "Entity revision conflict: "
                    f"expected={expected_revision}, "
                    f"actual={current_revision}"
                )

            if not updates:
                conn.commit()
                return self._entity_from_row(row)

            canonical_name = updates.get(
                "canonical_name",
                row["canonical_name"],
            )
            aliases = updates.get(
                "aliases",
                _json_load(row["aliases_json"], []),
            )
            aliases = self._entity_aliases(
                canonical_name,
                aliases,
            )
            description = updates.get(
                "description",
                row["description"],
            )
            metadata = updates.get(
                "metadata",
                _json_load(row["metadata_json"], {}),
            )
            now = _utc_now()

            conn.execute(
                """
                UPDATE novel_entities
                SET canonical_name = ?,
                    canonical_name_normalized = ?,
                    aliases_json = ?,
                    description = ?,
                    metadata_json = ?,
                    revision = revision + 1,
                    updated_at = ?
                WHERE novel_id = ? AND entity_id = ?
                """,
                (
                    canonical_name,
                    normalize_entity_name(canonical_name),
                    _json_dump(aliases),
                    description,
                    _json_dump(metadata),
                    now,
                    novel_id,
                    entity_id,
                ),
            )
            updated_row = conn.execute(
                """
                SELECT * FROM novel_entities
                WHERE novel_id = ? AND entity_id = ?
                """,
                (novel_id, entity_id),
            ).fetchone()
            entity = self._entity_from_row(updated_row)
            self._replace_entity_aliases(conn, entity, now)
            self._advance_canon_revision(
                conn,
                novel_id,
                now,
            )
            conn.commit()

        return entity

    @staticmethod
    def _resolve_entity_rows(
        conn: sqlite3.Connection,
        novel_id: str,
        name: str,
        *,
        entity_type: str | None = None,
    ) -> tuple[str | None, list[sqlite3.Row]]:
        normalized_query = normalize_entity_name(name)
        params: list[Any] = [
            novel_id,
            name,
            normalized_query,
        ]
        type_filter = ""
        if entity_type is not None:
            type_filter = " AND e.entity_type = ?"
            params.append(entity_type)

        rows = conn.execute(
            f"""
            SELECT e.*, a.alias, a.normalized_alias, a.alias_kind
            FROM novel_entity_aliases AS a
            JOIN novel_entities AS e
              ON e.novel_id = a.novel_id
             AND e.entity_id = a.entity_id
            WHERE a.novel_id = ?
              AND (a.alias = ? OR a.normalized_alias = ?)
              {type_filter}
            ORDER BY e.canonical_name_normalized, e.entity_id
            """,
            tuple(params),
        ).fetchall()

        strategies = (
            (
                "exact_canonical",
                lambda row: (
                    row["alias_kind"] == "canonical"
                    and row["alias"] == name
                ),
            ),
            (
                "exact_alias",
                lambda row: (
                    row["alias_kind"] == "alias"
                    and row["alias"] == name
                ),
            ),
            (
                "normalized_canonical",
                lambda row: (
                    row["alias_kind"] == "canonical"
                    and row["normalized_alias"] == normalized_query
                ),
            ),
            (
                "normalized_alias",
                lambda row: (
                    row["alias_kind"] == "alias"
                    and row["normalized_alias"] == normalized_query
                ),
            ),
        )

        for strategy, matches in strategies:
            candidates: list[sqlite3.Row] = []
            seen_ids: set[str] = set()
            for row in rows:
                if not matches(row) or row["entity_id"] in seen_ids:
                    continue
                seen_ids.add(row["entity_id"])
                candidates.append(row)
            if candidates:
                return strategy, candidates

        return None, []

    def resolve_entity(
        self,
        novel_id: str,
        payload: EntityResolveRequest,
    ) -> EntityResolution:
        if not self._project_exists(novel_id):
            raise NovelProjectNotFoundError(novel_id)

        normalized_query = normalize_entity_name(payload.name)
        with self._connect() as conn:
            strategy, rows = self._resolve_entity_rows(
                conn,
                novel_id,
                payload.name,
                entity_type=payload.entity_type,
            )

        candidates = [
            self._entity_from_row(row)
            for row in rows
        ]

        if len(candidates) == 1:
            return EntityResolution(
                query=payload.name,
                normalized_query=normalized_query,
                status="resolved",
                match_strategy=strategy,
                entity=candidates[0],
            )

        if len(candidates) > 1:
            return EntityResolution(
                query=payload.name,
                normalized_query=normalized_query,
                status="ambiguous",
                match_strategy=strategy,
                candidates=candidates,
            )

        return EntityResolution(
            query=payload.name,
            normalized_query=normalized_query,
            status="not_found",
        )

    def get_novel_plan(
        self,
        novel_id: str,
    ) -> NovelPlan:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT pl.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision
                FROM novel_plans AS pl
                JOIN novel_projects AS p
                  ON p.novel_id = pl.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = pl.novel_id
                WHERE pl.novel_id = ?
                """,
                (novel_id,),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise RuntimeError(
                f"Novel Plan is missing for novel {novel_id}"
            )
        return self._novel_plan_from_row(row)

    def update_novel_plan(
        self,
        novel_id: str,
        payload: NovelPlanUpdate,
        *,
        expected_project_revision: int | None = None,
        expected_story_bible_revision: int | None = None,
    ) -> NovelPlan:
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
                """
                SELECT pl.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision
                FROM novel_plans AS pl
                JOIN novel_projects AS p
                  ON p.novel_id = pl.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = pl.novel_id
                WHERE pl.novel_id = ?
                """,
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
                    f"Novel Plan is missing for novel {novel_id}"
                )

            current_revision = int(row["revision"])
            if (
                expected_revision is not None
                and expected_revision != current_revision
            ):
                raise NovelRevisionConflictError(
                    f"Novel Plan revision conflict: "
                    f"expected={expected_revision}, "
                    f"actual={current_revision}"
                )

            self._assert_expected_source_revisions(
                row,
                {
                    "current_project_revision": expected_project_revision,
                    "current_story_bible_revision": (
                        expected_story_bible_revision
                    ),
                },
                entity_name="Novel Plan",
            )

            if not updates:
                conn.commit()
                return self._novel_plan_from_row(row)

            column_map = {
                "story_premise": "story_premise",
                "core_conflict": "core_conflict",
                "central_question": "central_question",
                "ending_direction": "ending_direction",
                "themes": "themes_json",
                "main_plot": "main_plot_json",
                "character_arcs": "character_arcs_json",
                "volume_plans": "volume_plans_json",
                "metadata": "metadata_json",
            }
            json_fields = {
                "themes",
                "main_plot",
                "character_arcs",
                "volume_plans",
                "metadata",
            }
            assignments: list[str] = []
            values: list[Any] = []

            for field, value in updates.items():
                assignments.append(
                    f"{column_map[field]} = ?"
                )
                if field in json_fields:
                    if isinstance(value, list):
                        value = [
                            item.model_dump()
                            if hasattr(item, "model_dump")
                            else item
                            for item in value
                        ]
                    value = _json_dump(value)
                values.append(value)

            now = _utc_now()
            current_project_revision = int(
                row["current_project_revision"]
            )
            current_story_bible_revision = int(
                row["current_story_bible_revision"]
            )
            assignments.extend([
                "source_project_revision = ?",
                "source_story_bible_revision = ?",
                "revision = revision + 1",
                "updated_at = ?",
            ])
            values.extend([
                current_project_revision,
                current_story_bible_revision,
                now,
                novel_id,
            ])

            conn.execute(
                f"""
                UPDATE novel_plans
                SET {', '.join(assignments)}
                WHERE novel_id = ?
                """,
                tuple(values),
            )
            updated_row = conn.execute(
                """
                SELECT pl.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision
                FROM novel_plans AS pl
                JOIN novel_projects AS p
                  ON p.novel_id = pl.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = pl.novel_id
                WHERE pl.novel_id = ?
                """,
                (novel_id,),
            ).fetchone()
            plan = self._novel_plan_from_row(
                updated_row
            )
            self._insert_novel_plan_revision(
                conn,
                plan,
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

        return plan

    def list_novel_plan_revisions(
        self,
        novel_id: str,
        *,
        limit: int = 100,
    ) -> list[NovelPlanRevision]:
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
                FROM novel_plan_revisions
                WHERE novel_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (novel_id, normalized_limit),
            ).fetchall()

        return [
            self._plan_revision_from_row(row)
            for row in rows
        ]

    def get_novel_plan_revision(
        self,
        novel_id: str,
        revision: int,
    ) -> NovelPlanRevision:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT novel_id,
                       revision,
                       snapshot_json,
                       created_at
                FROM novel_plan_revisions
                WHERE novel_id = ?
                  AND revision = ?
                """,
                (novel_id, int(revision)),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise NovelProjectNotFoundError(
                f"{novel_id}:novel-plan:{revision}"
            )
        return self._plan_revision_from_row(row)


    def create_story_arc(
        self,
        novel_id: str,
        payload: StoryArcCreate,
        *,
        expected_project_revision: int | None = None,
        expected_story_bible_revision: int | None = None,
        expected_novel_plan_revision: int | None = None,
    ) -> StoryArc:
        arc_id = str(uuid.uuid4())
        now = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source_row = conn.execute(
                """
                SELECT
                    p.revision AS project_revision,
                    b.revision AS story_bible_revision,
                    pl.revision AS novel_plan_revision
                FROM novel_projects AS p
                JOIN story_bibles AS b
                  ON b.novel_id = p.novel_id
                JOIN novel_plans AS pl
                  ON pl.novel_id = p.novel_id
                WHERE p.novel_id = ?
                """,
                (novel_id,),
            ).fetchone()

            if source_row is None:
                raise NovelProjectNotFoundError(novel_id)

            self._assert_expected_source_revisions(
                source_row,
                {
                    "project_revision": expected_project_revision,
                    "story_bible_revision": expected_story_bible_revision,
                    "novel_plan_revision": expected_novel_plan_revision,
                },
                entity_name="Story Arc",
            )

            try:
                conn.execute(
                    """
                    INSERT INTO story_arcs (
                        arc_id,
                        novel_id,
                        volume_number,
                        arc_number,
                        revision,
                        source_project_revision,
                        source_story_bible_revision,
                        source_novel_plan_revision,
                        title,
                        objective,
                        summary,
                        opening_state,
                        closing_state,
                        core_conflict,
                        stakes,
                        turning_points_json,
                        character_progression_json,
                        plot_threads_json,
                        dependencies_json,
                        target_chapter_start,
                        target_chapter_end,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        arc_id,
                        novel_id,
                        payload.volume_number,
                        payload.arc_number,
                        int(source_row["project_revision"]),
                        int(source_row["story_bible_revision"]),
                        int(source_row["novel_plan_revision"]),
                        payload.title,
                        payload.objective,
                        payload.summary,
                        payload.opening_state,
                        payload.closing_state,
                        payload.core_conflict,
                        payload.stakes,
                        _json_dump([
                            item.model_dump()
                            for item in payload.turning_points
                        ]),
                        _json_dump([
                            item.model_dump()
                            for item in payload.character_progression
                        ]),
                        _json_dump(payload.plot_threads),
                        _json_dump(payload.dependencies),
                        payload.target_chapter_start,
                        payload.target_chapter_end,
                        _json_dump(payload.metadata),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise NovelRevisionConflictError(
                    "Story Arc position conflict: "
                    f"volume={payload.volume_number}, "
                    f"arc={payload.arc_number}"
                ) from exc

            row = self._get_story_arc_row(
                conn,
                novel_id,
                arc_id,
            )
            arc = self._story_arc_from_row(row)
            self._insert_story_arc_revision(
                conn,
                arc,
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

        return arc

    def list_story_arcs(
        self,
        novel_id: str,
        *,
        volume_number: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoryArc]:
        if not self._project_exists(novel_id):
            raise NovelProjectNotFoundError(novel_id)

        clauses = ["a.novel_id = ?"]
        params: list[Any] = [novel_id]

        if volume_number is not None:
            clauses.append("a.volume_number = ?")
            params.append(int(volume_number))

        params.extend([
            min(max(int(limit), 1), 500),
            max(int(offset), 0),
        ])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT a.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision,
                       pl.revision AS current_novel_plan_revision
                FROM story_arcs AS a
                JOIN novel_projects AS p
                  ON p.novel_id = a.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = a.novel_id
                JOIN novel_plans AS pl
                  ON pl.novel_id = a.novel_id
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    a.volume_number ASC,
                    a.arc_number ASC,
                    a.arc_id ASC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        return [
            self._story_arc_from_row(row)
            for row in rows
        ]

    def get_story_arc(
        self,
        novel_id: str,
        arc_id: str,
    ) -> StoryArc:
        with self._connect() as conn:
            row = self._get_story_arc_row(
                conn,
                novel_id,
                arc_id,
            )

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise NovelProjectNotFoundError(
                f"{novel_id}:story-arc:{arc_id}"
            )

        return self._story_arc_from_row(row)

    def update_story_arc(
        self,
        novel_id: str,
        arc_id: str,
        payload: StoryArcUpdate,
    ) -> StoryArc:
        updates = payload.model_dump(
            exclude_unset=True,
        )
        expected_revision = updates.pop(
            "expected_revision",
            None,
        )

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get_story_arc_row(
                conn,
                novel_id,
                arc_id,
            )

            if row is None:
                project = conn.execute(
                    """
                    SELECT novel_id
                    FROM novel_projects
                    WHERE novel_id = ?
                    """,
                    (novel_id,),
                ).fetchone()

                if project is None:
                    raise NovelProjectNotFoundError(novel_id)

                raise NovelProjectNotFoundError(
                    f"{novel_id}:story-arc:{arc_id}"
                )

            current_revision = int(row["revision"])

            if (
                expected_revision is not None
                and expected_revision != current_revision
            ):
                raise NovelRevisionConflictError(
                    "Story Arc revision conflict: "
                    f"expected={expected_revision}, "
                    f"actual={current_revision}"
                )

            if not updates:
                conn.commit()
                return self._story_arc_from_row(row)

            column_map = {
                "volume_number": "volume_number",
                "arc_number": "arc_number",
                "title": "title",
                "objective": "objective",
                "summary": "summary",
                "opening_state": "opening_state",
                "closing_state": "closing_state",
                "core_conflict": "core_conflict",
                "stakes": "stakes",
                "turning_points": "turning_points_json",
                "character_progression": "character_progression_json",
                "plot_threads": "plot_threads_json",
                "dependencies": "dependencies_json",
                "target_chapter_start": "target_chapter_start",
                "target_chapter_end": "target_chapter_end",
                "metadata": "metadata_json",
            }

            json_fields = {
                "turning_points",
                "character_progression",
                "plot_threads",
                "dependencies",
                "metadata",
            }

            assignments: list[str] = []
            values: list[Any] = []

            for field, value in updates.items():
                assignments.append(
                    f"{column_map[field]} = ?"
                )

                if field in json_fields:
                    if isinstance(value, list):
                        value = [
                            item.model_dump()
                            if hasattr(item, "model_dump")
                            else item
                            for item in value
                        ]
                    value = _json_dump(value)

                values.append(value)

            now = _utc_now()

            assignments.extend([
                "source_project_revision = ?",
                "source_story_bible_revision = ?",
                "source_novel_plan_revision = ?",
                "revision = revision + 1",
                "updated_at = ?",
            ])

            values.extend([
                int(row["current_project_revision"]),
                int(row["current_story_bible_revision"]),
                int(row["current_novel_plan_revision"]),
                now,
                novel_id,
                arc_id,
            ])

            try:
                conn.execute(
                    f"""
                    UPDATE story_arcs
                    SET {', '.join(assignments)}
                    WHERE novel_id = ?
                      AND arc_id = ?
                    """,
                    tuple(values),
                )
            except sqlite3.IntegrityError as exc:
                raise NovelRevisionConflictError(
                    "Story Arc position conflict"
                ) from exc

            updated_row = self._get_story_arc_row(
                conn,
                novel_id,
                arc_id,
            )
            arc = self._story_arc_from_row(
                updated_row
            )
            self._insert_story_arc_revision(
                conn,
                arc,
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

        return arc

    def list_story_arc_revisions(
        self,
        novel_id: str,
        arc_id: str,
        *,
        limit: int = 100,
    ) -> list[StoryArcRevision]:
        self.get_story_arc(
            novel_id,
            arc_id,
        )

        normalized_limit = min(
            max(int(limit), 1),
            500,
        )

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    arc_id,
                    novel_id,
                    revision,
                    snapshot_json,
                    created_at
                FROM story_arc_revisions
                WHERE novel_id = ?
                  AND arc_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (
                    novel_id,
                    arc_id,
                    normalized_limit,
                ),
            ).fetchall()

        return [
            self._story_arc_revision_from_row(row)
            for row in rows
        ]

    def get_story_arc_revision(
        self,
        novel_id: str,
        arc_id: str,
        revision: int,
    ) -> StoryArcRevision:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    arc_id,
                    novel_id,
                    revision,
                    snapshot_json,
                    created_at
                FROM story_arc_revisions
                WHERE novel_id = ?
                  AND arc_id = ?
                  AND revision = ?
                """,
                (
                    novel_id,
                    arc_id,
                    int(revision),
                ),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)

            raise NovelProjectNotFoundError(
                f"{novel_id}:story-arc:"
                f"{arc_id}:{revision}"
            )

        return self._story_arc_revision_from_row(
            row
        )

    @staticmethod
    def _get_story_arc_row(
        conn: sqlite3.Connection,
        novel_id: str,
        arc_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT a.*,
                   p.revision AS current_project_revision,
                   b.revision AS current_story_bible_revision,
                   pl.revision AS current_novel_plan_revision
            FROM story_arcs AS a
            JOIN novel_projects AS p
              ON p.novel_id = a.novel_id
            JOIN story_bibles AS b
              ON b.novel_id = a.novel_id
            JOIN novel_plans AS pl
              ON pl.novel_id = a.novel_id
            WHERE a.novel_id = ?
              AND a.arc_id = ?
            """,
            (
                novel_id,
                arc_id,
            ),
        ).fetchone()

    def _insert_story_arc_revision(
        self,
        conn: sqlite3.Connection,
        arc: StoryArc,
        created_at: str,
    ) -> None:
        snapshot = arc.model_copy(
            update={"is_stale": False}
        )

        conn.execute(
            """
            INSERT INTO story_arc_revisions (
                arc_id,
                novel_id,
                revision,
                snapshot_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                snapshot.arc_id,
                snapshot.novel_id,
                snapshot.revision,
                _json_dump(
                    snapshot.model_dump()
                ),
                created_at,
            ),
        )

    @staticmethod
    def _story_arc_from_row(
        row: sqlite3.Row,
    ) -> StoryArc:
        source_project_revision = int(
            row["source_project_revision"]
        )
        source_story_bible_revision = int(
            row["source_story_bible_revision"]
        )
        source_novel_plan_revision = int(
            row["source_novel_plan_revision"]
        )

        return StoryArc(
            arc_id=row["arc_id"],
            novel_id=row["novel_id"],
            volume_number=int(
                row["volume_number"]
            ),
            arc_number=int(
                row["arc_number"]
            ),
            revision=int(row["revision"]),
            source_project_revision=(
                source_project_revision
            ),
            source_story_bible_revision=(
                source_story_bible_revision
            ),
            source_novel_plan_revision=(
                source_novel_plan_revision
            ),
            is_stale=(
                source_project_revision
                != int(
                    row[
                        "current_project_revision"
                    ]
                )
                or source_story_bible_revision
                != int(
                    row[
                        "current_story_bible_revision"
                    ]
                )
                or source_novel_plan_revision
                != int(
                    row[
                        "current_novel_plan_revision"
                    ]
                )
            ),
            title=row["title"],
            objective=row["objective"],
            summary=row["summary"],
            opening_state=row["opening_state"],
            closing_state=row["closing_state"],
            core_conflict=row["core_conflict"],
            stakes=row["stakes"],
            turning_points=_json_load(
                row["turning_points_json"],
                [],
            ),
            character_progression=_json_load(
                row[
                    "character_progression_json"
                ],
                [],
            ),
            plot_threads=_json_load(
                row["plot_threads_json"],
                [],
            ),
            dependencies=_json_load(
                row["dependencies_json"],
                [],
            ),
            target_chapter_start=(
                int(row["target_chapter_start"])
                if row["target_chapter_start"]
                is not None
                else None
            ),
            target_chapter_end=(
                int(row["target_chapter_end"])
                if row["target_chapter_end"]
                is not None
                else None
            ),
            metadata=_json_load(
                row["metadata_json"],
                {},
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _story_arc_revision_from_row(
        row: sqlite3.Row,
    ) -> StoryArcRevision:
        snapshot = StoryArc.model_validate(
            json.loads(row["snapshot_json"])
        )

        return StoryArcRevision(
            arc_id=row["arc_id"],
            novel_id=row["novel_id"],
            revision=int(row["revision"]),
            snapshot=snapshot,
            created_at=row["created_at"],
        )


    def create_chapter_plan(
        self,
        novel_id: str,
        payload: ChapterPlanCreate,
        *,
        expected_project_revision: int | None = None,
        expected_story_bible_revision: int | None = None,
        expected_novel_plan_revision: int | None = None,
        expected_story_arc_revision: int | None = None,
    ) -> ChapterPlan:
        chapter_plan_id = str(uuid.uuid4())
        now = _utc_now()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source_row = self._get_chapter_source_row(
                conn,
                novel_id,
                payload.arc_id,
            )

            if source_row is None:
                project = conn.execute(
                    """
                    SELECT novel_id
                    FROM novel_projects
                    WHERE novel_id = ?
                    """,
                    (novel_id,),
                ).fetchone()

                if project is None:
                    raise NovelProjectNotFoundError(novel_id)

                raise NovelProjectNotFoundError(
                    f"{novel_id}:story-arc:{payload.arc_id}"
                )

            self._assert_expected_source_revisions(
                source_row,
                {
                    "project_revision": expected_project_revision,
                    "story_bible_revision": expected_story_bible_revision,
                    "novel_plan_revision": expected_novel_plan_revision,
                    "story_arc_revision": expected_story_arc_revision,
                },
                entity_name="Chapter Plan",
            )

            try:
                conn.execute(
                    """
                    INSERT INTO chapter_plans (
                        chapter_plan_id,
                        novel_id,
                        arc_id,
                        chapter_number,
                        revision,
                        source_project_revision,
                        source_story_bible_revision,
                        source_novel_plan_revision,
                        source_story_arc_revision,
                        title,
                        objective,
                        summary,
                        pov_character_id,
                        pov_character_name,
                        opening_state,
                        closing_state,
                        conflict,
                        reveal,
                        hook,
                        scene_beats_json,
                        continuity_dependencies_json,
                        target_word_count,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        chapter_plan_id,
                        novel_id,
                        payload.arc_id,
                        payload.chapter_number,
                        int(source_row["project_revision"]),
                        int(source_row["story_bible_revision"]),
                        int(source_row["novel_plan_revision"]),
                        int(source_row["story_arc_revision"]),
                        payload.title,
                        payload.objective,
                        payload.summary,
                        payload.pov_character_id,
                        payload.pov_character_name,
                        payload.opening_state,
                        payload.closing_state,
                        payload.conflict,
                        payload.reveal,
                        payload.hook,
                        _json_dump([
                            item.model_dump()
                            for item in payload.scene_beats
                        ]),
                        _json_dump(payload.continuity_dependencies),
                        payload.target_word_count,
                        _json_dump(payload.metadata),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise NovelRevisionConflictError(
                    "Chapter Plan position conflict: "
                    f"chapter={payload.chapter_number}"
                ) from exc

            row = self._get_chapter_plan_row(
                conn,
                novel_id,
                chapter_plan_id,
            )
            plan = self._chapter_plan_from_row(row)
            self._insert_chapter_plan_revision(
                conn,
                plan,
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

        return plan

    def list_chapter_plans(
        self,
        novel_id: str,
        *,
        arc_id: str | None = None,
        volume_number: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChapterPlan]:
        if not self._project_exists(novel_id):
            raise NovelProjectNotFoundError(novel_id)

        clauses = ["c.novel_id = ?"]
        params: list[Any] = [novel_id]

        if arc_id is not None:
            clauses.append("c.arc_id = ?")
            params.append(arc_id)

        if volume_number is not None:
            clauses.append("a.volume_number = ?")
            params.append(int(volume_number))

        params.extend([
            min(max(int(limit), 1), 500),
            max(int(offset), 0),
        ])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision,
                       pl.revision AS current_novel_plan_revision,
                       a.revision AS current_story_arc_revision,
                       a.volume_number AS current_volume_number,
                       a.arc_number AS current_arc_number
                FROM chapter_plans AS c
                JOIN novel_projects AS p
                  ON p.novel_id = c.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = c.novel_id
                JOIN novel_plans AS pl
                  ON pl.novel_id = c.novel_id
                JOIN story_arcs AS a
                  ON a.novel_id = c.novel_id
                 AND a.arc_id = c.arc_id
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    c.chapter_number ASC,
                    c.chapter_plan_id ASC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        return [
            self._chapter_plan_from_row(row)
            for row in rows
        ]

    def get_chapter_plan(
        self,
        novel_id: str,
        chapter_plan_id: str,
    ) -> ChapterPlan:
        with self._connect() as conn:
            row = self._get_chapter_plan_row(
                conn,
                novel_id,
                chapter_plan_id,
            )

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)
            raise NovelProjectNotFoundError(
                f"{novel_id}:chapter-plan:{chapter_plan_id}"
            )

        return self._chapter_plan_from_row(row)

    def update_chapter_plan(
        self,
        novel_id: str,
        chapter_plan_id: str,
        payload: ChapterPlanUpdate,
    ) -> ChapterPlan:
        updates = payload.model_dump(
            exclude_unset=True,
        )
        expected_revision = updates.pop(
            "expected_revision",
            None,
        )

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get_chapter_plan_row(
                conn,
                novel_id,
                chapter_plan_id,
            )

            if row is None:
                project = conn.execute(
                    """
                    SELECT novel_id
                    FROM novel_projects
                    WHERE novel_id = ?
                    """,
                    (novel_id,),
                ).fetchone()

                if project is None:
                    raise NovelProjectNotFoundError(novel_id)

                raise NovelProjectNotFoundError(
                    f"{novel_id}:chapter-plan:{chapter_plan_id}"
                )

            current_revision = int(row["revision"])

            if (
                expected_revision is not None
                and expected_revision != current_revision
            ):
                raise NovelRevisionConflictError(
                    "Chapter Plan revision conflict: "
                    f"expected={expected_revision}, "
                    f"actual={current_revision}"
                )

            if not updates:
                conn.commit()
                return self._chapter_plan_from_row(row)

            target_arc_id = updates.get(
                "arc_id",
                row["arc_id"],
            )
            source_row = self._get_chapter_source_row(
                conn,
                novel_id,
                target_arc_id,
            )

            if source_row is None:
                raise NovelProjectNotFoundError(
                    f"{novel_id}:story-arc:{target_arc_id}"
                )

            column_map = {
                "arc_id": "arc_id",
                "chapter_number": "chapter_number",
                "title": "title",
                "objective": "objective",
                "summary": "summary",
                "pov_character_id": "pov_character_id",
                "pov_character_name": "pov_character_name",
                "opening_state": "opening_state",
                "closing_state": "closing_state",
                "conflict": "conflict",
                "reveal": "reveal",
                "hook": "hook",
                "scene_beats": "scene_beats_json",
                "continuity_dependencies": "continuity_dependencies_json",
                "target_word_count": "target_word_count",
                "metadata": "metadata_json",
            }

            json_fields = {
                "scene_beats",
                "continuity_dependencies",
                "metadata",
            }

            assignments: list[str] = []
            values: list[Any] = []

            for field, value in updates.items():
                assignments.append(
                    f"{column_map[field]} = ?"
                )

                if field in json_fields:
                    if isinstance(value, list):
                        value = [
                            item.model_dump()
                            if hasattr(item, "model_dump")
                            else item
                            for item in value
                        ]
                    value = _json_dump(value)

                values.append(value)

            now = _utc_now()

            assignments.extend([
                "source_project_revision = ?",
                "source_story_bible_revision = ?",
                "source_novel_plan_revision = ?",
                "source_story_arc_revision = ?",
                "revision = revision + 1",
                "updated_at = ?",
            ])

            values.extend([
                int(source_row["project_revision"]),
                int(source_row["story_bible_revision"]),
                int(source_row["novel_plan_revision"]),
                int(source_row["story_arc_revision"]),
                now,
                novel_id,
                chapter_plan_id,
            ])

            try:
                conn.execute(
                    f"""
                    UPDATE chapter_plans
                    SET {', '.join(assignments)}
                    WHERE novel_id = ?
                      AND chapter_plan_id = ?
                    """,
                    tuple(values),
                )
            except sqlite3.IntegrityError as exc:
                raise NovelRevisionConflictError(
                    "Chapter Plan position conflict"
                ) from exc

            updated_row = self._get_chapter_plan_row(
                conn,
                novel_id,
                chapter_plan_id,
            )
            plan = self._chapter_plan_from_row(
                updated_row
            )
            self._insert_chapter_plan_revision(
                conn,
                plan,
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

        return plan

    def list_chapter_plan_revisions(
        self,
        novel_id: str,
        chapter_plan_id: str,
        *,
        limit: int = 100,
    ) -> list[ChapterPlanRevision]:
        self.get_chapter_plan(
            novel_id,
            chapter_plan_id,
        )

        normalized_limit = min(
            max(int(limit), 1),
            500,
        )

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    chapter_plan_id,
                    novel_id,
                    revision,
                    snapshot_json,
                    created_at
                FROM chapter_plan_revisions
                WHERE novel_id = ?
                  AND chapter_plan_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (
                    novel_id,
                    chapter_plan_id,
                    normalized_limit,
                ),
            ).fetchall()

        return [
            self._chapter_plan_revision_from_row(row)
            for row in rows
        ]

    def get_chapter_plan_revision(
        self,
        novel_id: str,
        chapter_plan_id: str,
        revision: int,
    ) -> ChapterPlanRevision:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    chapter_plan_id,
                    novel_id,
                    revision,
                    snapshot_json,
                    created_at
                FROM chapter_plan_revisions
                WHERE novel_id = ?
                  AND chapter_plan_id = ?
                  AND revision = ?
                """,
                (
                    novel_id,
                    chapter_plan_id,
                    int(revision),
                ),
            ).fetchone()

        if row is None:
            if not self._project_exists(novel_id):
                raise NovelProjectNotFoundError(novel_id)

            raise NovelProjectNotFoundError(
                f"{novel_id}:chapter-plan:"
                f"{chapter_plan_id}:{revision}"
            )

        return self._chapter_plan_revision_from_row(
            row
        )

    @staticmethod
    def _get_chapter_source_row(
        conn: sqlite3.Connection,
        novel_id: str,
        arc_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT
                p.revision AS project_revision,
                b.revision AS story_bible_revision,
                pl.revision AS novel_plan_revision,
                a.revision AS story_arc_revision,
                a.volume_number AS volume_number,
                a.arc_number AS arc_number
            FROM novel_projects AS p
            JOIN story_bibles AS b
              ON b.novel_id = p.novel_id
            JOIN novel_plans AS pl
              ON pl.novel_id = p.novel_id
            JOIN story_arcs AS a
              ON a.novel_id = p.novel_id
             AND a.arc_id = ?
            WHERE p.novel_id = ?
            """,
            (
                arc_id,
                novel_id,
            ),
        ).fetchone()

    @staticmethod
    def _get_chapter_plan_row(
        conn: sqlite3.Connection,
        novel_id: str,
        chapter_plan_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT c.*,
                   p.revision AS current_project_revision,
                   b.revision AS current_story_bible_revision,
                   pl.revision AS current_novel_plan_revision,
                   a.revision AS current_story_arc_revision,
                   a.volume_number AS current_volume_number,
                   a.arc_number AS current_arc_number
            FROM chapter_plans AS c
            JOIN novel_projects AS p
              ON p.novel_id = c.novel_id
            JOIN story_bibles AS b
              ON b.novel_id = c.novel_id
            JOIN novel_plans AS pl
              ON pl.novel_id = c.novel_id
            JOIN story_arcs AS a
              ON a.novel_id = c.novel_id
             AND a.arc_id = c.arc_id
            WHERE c.novel_id = ?
              AND c.chapter_plan_id = ?
            """,
            (
                novel_id,
                chapter_plan_id,
            ),
        ).fetchone()

    def _insert_chapter_plan_revision(
        self,
        conn: sqlite3.Connection,
        plan: ChapterPlan,
        created_at: str,
    ) -> None:
        snapshot = plan.model_copy(
            update={"is_stale": False}
        )

        conn.execute(
            """
            INSERT INTO chapter_plan_revisions (
                chapter_plan_id,
                novel_id,
                revision,
                snapshot_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                snapshot.chapter_plan_id,
                snapshot.novel_id,
                snapshot.revision,
                _json_dump(
                    snapshot.model_dump()
                ),
                created_at,
            ),
        )

    @staticmethod
    def _chapter_plan_from_row(
        row: sqlite3.Row,
    ) -> ChapterPlan:
        source_project_revision = int(
            row["source_project_revision"]
        )
        source_story_bible_revision = int(
            row["source_story_bible_revision"]
        )
        source_novel_plan_revision = int(
            row["source_novel_plan_revision"]
        )
        source_story_arc_revision = int(
            row["source_story_arc_revision"]
        )

        return ChapterPlan(
            chapter_plan_id=row["chapter_plan_id"],
            novel_id=row["novel_id"],
            arc_id=row["arc_id"],
            volume_number=int(
                row["current_volume_number"]
            ),
            arc_number=int(
                row["current_arc_number"]
            ),
            chapter_number=int(
                row["chapter_number"]
            ),
            revision=int(row["revision"]),
            source_project_revision=(
                source_project_revision
            ),
            source_story_bible_revision=(
                source_story_bible_revision
            ),
            source_novel_plan_revision=(
                source_novel_plan_revision
            ),
            source_story_arc_revision=(
                source_story_arc_revision
            ),
            is_stale=(
                source_project_revision
                != int(
                    row["current_project_revision"]
                )
                or source_story_bible_revision
                != int(
                    row[
                        "current_story_bible_revision"
                    ]
                )
                or source_novel_plan_revision
                != int(
                    row["current_novel_plan_revision"]
                )
                or source_story_arc_revision
                != int(
                    row["current_story_arc_revision"]
                )
            ),
            title=row["title"],
            objective=row["objective"],
            summary=row["summary"],
            pov_character_id=row["pov_character_id"],
            pov_character_name=row["pov_character_name"],
            opening_state=row["opening_state"],
            closing_state=row["closing_state"],
            conflict=row["conflict"],
            reveal=row["reveal"],
            hook=row["hook"],
            scene_beats=_json_load(
                row["scene_beats_json"],
                [],
            ),
            continuity_dependencies=_json_load(
                row[
                    "continuity_dependencies_json"
                ],
                [],
            ),
            target_word_count=int(
                row["target_word_count"]
            ),
            metadata=_json_load(
                row["metadata_json"],
                {},
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _chapter_plan_revision_from_row(
        row: sqlite3.Row,
    ) -> ChapterPlanRevision:
        snapshot = ChapterPlan.model_validate(
            json.loads(row["snapshot_json"])
        )

        return ChapterPlanRevision(
            chapter_plan_id=row["chapter_plan_id"],
            novel_id=row["novel_id"],
            revision=int(row["revision"]),
            snapshot=snapshot,
            created_at=row["created_at"],
        )

    def _backfill_novel_plans(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        rows = conn.execute(
            """
            SELECT p.novel_id,
                   p.premise,
                   p.revision AS project_revision,
                   b.revision AS story_bible_revision
            FROM novel_projects AS p
            JOIN story_bibles AS b
              ON b.novel_id = p.novel_id
            LEFT JOIN novel_plans AS pl
              ON pl.novel_id = p.novel_id
            WHERE pl.novel_id IS NULL
            ORDER BY p.novel_id ASC
            """
        ).fetchall()

        for row in rows:
            now = _utc_now()
            conn.execute(
                """
                INSERT INTO novel_plans (
                    novel_id,
                    revision,
                    source_project_revision,
                    source_story_bible_revision,
                    story_premise,
                    created_at,
                    updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    row["novel_id"],
                    int(row["project_revision"]),
                    int(row["story_bible_revision"]),
                    row["premise"],
                    now,
                    now,
                ),
            )
            plan_row = conn.execute(
                """
                SELECT pl.*,
                       p.revision AS current_project_revision,
                       b.revision AS current_story_bible_revision
                FROM novel_plans AS pl
                JOIN novel_projects AS p
                  ON p.novel_id = pl.novel_id
                JOIN story_bibles AS b
                  ON b.novel_id = pl.novel_id
                WHERE pl.novel_id = ?
                """,
                (row["novel_id"],),
            ).fetchone()
            self._insert_novel_plan_revision(
                conn,
                self._novel_plan_from_row(
                    plan_row
                ),
                now,
            )

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

    def _insert_novel_plan_revision(
        self,
        conn: sqlite3.Connection,
        plan: NovelPlan,
        created_at: str,
    ) -> None:
        snapshot = plan.model_copy(
            update={"is_stale": False}
        )
        conn.execute(
            """
            INSERT INTO novel_plan_revisions (
                novel_id,
                revision,
                snapshot_json,
                created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                snapshot.novel_id,
                snapshot.revision,
                _json_dump(
                    snapshot.model_dump()
                ),
                created_at,
            ),
        )

    @staticmethod
    def _novel_plan_from_row(
        row: sqlite3.Row,
    ) -> NovelPlan:
        current_project_revision = int(
            row["current_project_revision"]
        )
        current_story_bible_revision = int(
            row["current_story_bible_revision"]
        )
        source_project_revision = int(
            row["source_project_revision"]
        )
        source_story_bible_revision = int(
            row["source_story_bible_revision"]
        )
        return NovelPlan(
            novel_id=row["novel_id"],
            revision=int(row["revision"]),
            source_project_revision=(
                source_project_revision
            ),
            source_story_bible_revision=(
                source_story_bible_revision
            ),
            is_stale=(
                source_project_revision
                != current_project_revision
                or source_story_bible_revision
                != current_story_bible_revision
            ),
            story_premise=row["story_premise"],
            core_conflict=row["core_conflict"],
            central_question=row["central_question"],
            ending_direction=row["ending_direction"],
            themes=_json_load(
                row["themes_json"],
                [],
            ),
            main_plot=_json_load(
                row["main_plot_json"],
                [],
            ),
            character_arcs=_json_load(
                row["character_arcs_json"],
                [],
            ),
            volume_plans=_json_load(
                row["volume_plans_json"],
                [],
            ),
            metadata=_json_load(
                row["metadata_json"],
                {},
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _plan_revision_from_row(
        row: sqlite3.Row,
    ) -> NovelPlanRevision:
        snapshot = NovelPlan.model_validate(
            json.loads(row["snapshot_json"])
        )
        return NovelPlanRevision(
            novel_id=row["novel_id"],
            revision=int(row["revision"]),
            snapshot=snapshot,
            created_at=row["created_at"],
        )

    @staticmethod
    def _entity_from_row(
        row: sqlite3.Row,
    ) -> NovelEntity:
        return NovelEntity(
            entity_id=row["entity_id"],
            novel_id=row["novel_id"],
            entity_type=row["entity_type"],
            canonical_name=row["canonical_name"],
            aliases=_json_load(row["aliases_json"], []),
            description=row["description"],
            revision=int(row["revision"]),
            metadata=_json_load(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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
