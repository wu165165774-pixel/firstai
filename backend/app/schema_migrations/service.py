from __future__ import annotations

import hashlib
import sqlite3

from datetime import datetime, timezone
from pathlib import Path

from app.backup.service import BackupError, BackupService
from app.schema_version import CURRENT_SCHEMA_VERSION, LEGACY_SCHEMA_VERSION
from app.version import APP_VERSION

from .contracts import AUTHORITIES, SchemaAuthority
from .schemas import (
    AuthorityMigrationStatus,
    SchemaMigrationStatus,
    SchemaUpgradeResult,
)


class SchemaMigrationError(RuntimeError):
    pass


class SchemaMigrationService:
    CURRENT_VERSION = CURRENT_SCHEMA_VERSION
    LEGACY_VERSION = LEGACY_SCHEMA_VERSION
    LEDGER_TABLE = "novelforge_schema_migrations"
    MIGRATION_NAME = "baseline_explicit_schema_version"

    @classmethod
    def _checksum(cls, authority: str) -> str:
        value = (
            f"{authority}:{cls.CURRENT_VERSION}:{cls.MIGRATION_NAME}"
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_root(data_root: str | Path | None) -> Path | None:
        if data_root is None:
            return None
        raw = Path(data_root).expanduser()
        if raw.is_symlink():
            raise SchemaMigrationError(
                "Migration data root must not be a symbolic link."
            )
        root = raw.resolve()
        if not root.is_dir():
            raise SchemaMigrationError(
                "Migration data root must be an existing directory."
            )
        return root

    @staticmethod
    def _ensure_database_file(path: Path, database: str) -> None:
        if path.is_symlink() or not path.is_file():
            raise SchemaMigrationError(
                f"Schema authority is missing or invalid: {database}"
            )

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
            timeout=30.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @classmethod
    def _contract_error(
        cls,
        connection: sqlite3.Connection,
        authority: SchemaAuthority,
        *,
        full_integrity: bool,
    ) -> str | None:
        if full_integrity:
            integrity = [
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check")
            ]
            if integrity != ["ok"]:
                return "integrity_check_failed"
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                return "foreign_key_check_failed"

        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table, required_columns in authority.required_columns.items():
            if table not in tables:
                return f"missing_table:{table}"
            actual_columns = {
                str(row[1])
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                )
            }
            missing = sorted(required_columns - actual_columns)
            if missing:
                return f"missing_column:{table}.{missing[0]}"
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing_indexes = sorted(authority.required_indexes - indexes)
        if missing_indexes:
            return f"missing_index:{missing_indexes[0]}"
        return None

    @classmethod
    def _ledger_error(
        cls,
        connection: sqlite3.Connection,
        authority: SchemaAuthority,
        current_version: int,
    ) -> str | None:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (cls.LEDGER_TABLE,),
        ).fetchone()
        if current_version == cls.LEGACY_VERSION:
            return (
                None
                if table is None
                else "migration_ledger_unexpected_for_legacy"
            )
        if table is None:
            return "migration_ledger_missing"
        rows = connection.execute(
            f"SELECT authority, version, name, checksum "
            f"FROM {cls.LEDGER_TABLE} ORDER BY version"
        ).fetchall()
        if len(rows) != current_version:
            return "migration_ledger_version_mismatch"
        expected_versions = list(range(1, current_version + 1))
        if [int(row["version"]) for row in rows] != expected_versions:
            return "migration_ledger_sequence_invalid"
        baseline = rows[0]
        if (
            str(baseline["authority"]) != authority.key
            or str(baseline["name"]) != cls.MIGRATION_NAME
            or str(baseline["checksum"]) != cls._checksum(authority.key)
        ):
            return "migration_ledger_checksum_mismatch"
        return None

    def _authority_status(
        self,
        authority: SchemaAuthority,
        path: Path,
        *,
        full_integrity: bool = True,
    ) -> AuthorityMigrationStatus:
        if path.is_symlink() or not path.is_file():
            return AuthorityMigrationStatus(
                authority=authority.key,
                database=authority.filename,
                current_version=0,
                target_version=self.CURRENT_VERSION,
                state="missing",
                contract_valid=False,
                ledger_valid=False,
                detail="database_missing_or_invalid",
            )
        try:
            with self._connect_readonly(path) as connection:
                current_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                contract_error = self._contract_error(
                    connection,
                    authority,
                    full_integrity=full_integrity,
                )
                ledger_error = self._ledger_error(
                    connection,
                    authority,
                    current_version,
                )
        except sqlite3.DatabaseError:
            return AuthorityMigrationStatus(
                authority=authority.key,
                database=authority.filename,
                current_version=0,
                target_version=self.CURRENT_VERSION,
                state="schema_incomplete",
                contract_valid=False,
                ledger_valid=False,
                detail="database_invalid",
            )

        if current_version > self.CURRENT_VERSION:
            state = "unsupported_newer"
            detail = "database_version_is_newer_than_application"
        elif contract_error is not None:
            state = "schema_incomplete"
            detail = contract_error
        elif ledger_error is not None:
            state = "schema_incomplete"
            detail = ledger_error
        elif current_version == self.CURRENT_VERSION:
            state = "current"
            detail = None
        else:
            state = "upgrade_required"
            detail = None

        return AuthorityMigrationStatus(
            authority=authority.key,
            database=authority.filename,
            current_version=current_version,
            target_version=self.CURRENT_VERSION,
            state=state,
            contract_valid=contract_error is None,
            ledger_valid=ledger_error is None,
            detail=detail,
        )

    def _status(
        self,
        *,
        data_root: str | Path | None = None,
        full_integrity: bool,
    ) -> SchemaMigrationStatus:
        root = self._safe_root(data_root)
        statuses = [
            self._authority_status(
                authority,
                authority.resolve_path(root),
                full_integrity=full_integrity,
            )
            for authority in AUTHORITIES
        ]
        return SchemaMigrationStatus(
            target_version=self.CURRENT_VERSION,
            authorities=statuses,
            ready=all(item.state == "current" for item in statuses),
        )

    def status(
        self,
        *,
        data_root: str | Path | None = None,
    ) -> SchemaMigrationStatus:
        return self._status(
            data_root=data_root,
            full_integrity=True,
        )

    @staticmethod
    def _bootstrap_authority(
        authority: SchemaAuthority,
        path: Path,
    ) -> None:
        value = str(path)
        if authority.key == "novels":
            from app.manuscripts.storage import ManuscriptStorage
            from app.novels.storage import NovelProjectStorage

            NovelProjectStorage(value)
            ManuscriptStorage(value)
        elif authority.key == "workflow":
            from app.orchestrator.storage import NovelOrchestrationStorage
            from app.workflows.async_queue import WorkflowAsyncQueue

            WorkflowAsyncQueue(value)
            NovelOrchestrationStorage(value)
        elif authority.key == "memory":
            from app.memory.storage.sqlite import SQLiteMemoryStorage

            SQLiteMemoryStorage(value)
        elif authority.key == "external_knowledge":
            from app.knowledge.storage import SQLiteExternalKnowledgeStorage

            SQLiteExternalKnowledgeStorage(value)
        elif authority.key == "temporal_graph":
            from app.temporal_graph.storage import TemporalGraphStorage

            TemporalGraphStorage(value)
        else:
            raise SchemaMigrationError(
                f"Unknown schema authority: {authority.key}"
            )

    def _apply_version_1(
        self,
        connection: sqlite3.Connection,
        authority: SchemaAuthority,
    ) -> None:
        _ = connection, authority

    def _upgrade_authority(
        self,
        authority: SchemaAuthority,
        path: Path,
    ) -> bool:
        try:
            connection = sqlite3.connect(path, timeout=30.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version == self.CURRENT_VERSION:
                connection.rollback()
                return False
            if current_version != self.LEGACY_VERSION:
                raise SchemaMigrationError(
                    f"Unsupported schema version: {authority.filename}"
                )
            connection.execute(
                f"""
                CREATE TABLE {self.LEDGER_TABLE} (
                    authority TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    application_version TEXT NOT NULL,
                    PRIMARY KEY(authority, version)
                )
                """
            )
            self._apply_version_1(connection, authority)
            connection.execute(
                f"INSERT INTO {self.LEDGER_TABLE} ("
                "authority, version, name, checksum, applied_at, "
                "application_version) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    authority.key,
                    self.CURRENT_VERSION,
                    self.MIGRATION_NAME,
                    self._checksum(authority.key),
                    datetime.now(timezone.utc).isoformat(),
                    APP_VERSION,
                ),
            )
            connection.execute(
                f"PRAGMA user_version = {self.CURRENT_VERSION}"
            )
            connection.commit()
            return True
        except SchemaMigrationError:
            if "connection" in locals():
                connection.rollback()
            raise
        except Exception as exc:
            if "connection" in locals():
                connection.rollback()
            raise SchemaMigrationError(
                f"Schema migration failed: {authority.filename}"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()

    def upgrade(
        self,
        *,
        data_root: str | Path,
        backup_dir: str | Path,
        offline_confirmed: bool = False,
    ) -> SchemaUpgradeResult:
        if not offline_confirmed:
            raise SchemaMigrationError(
                "Offline maintenance must be explicitly confirmed."
            )
        root = self._safe_root(data_root)
        assert root is not None
        try:
            backup = BackupService().verify(backup_dir)
        except BackupError as exc:
            raise SchemaMigrationError(
                "A valid NovelForge backup is required before migration."
            ) from exc

        paths = {
            authority.key: authority.resolve_path(root)
            for authority in AUTHORITIES
        }
        for authority in AUTHORITIES:
            self._ensure_database_file(
                paths[authority.key],
                authority.filename,
            )
            status = self._authority_status(
                authority,
                paths[authority.key],
            )
            if status.state == "unsupported_newer":
                raise SchemaMigrationError(
                    f"Database is newer than this application: "
                    f"{authority.filename}"
                )
            if (
                status.current_version == self.CURRENT_VERSION
                and status.state != "current"
            ):
                raise SchemaMigrationError(
                    f"Current schema metadata is invalid: "
                    f"{authority.filename}"
                )

        for authority in AUTHORITIES:
            status = self._authority_status(
                authority,
                paths[authority.key],
            )
            if status.current_version == self.LEGACY_VERSION:
                self._bootstrap_authority(
                    authority,
                    paths[authority.key],
                )

        preflight = self.status(data_root=root)
        invalid = [
            item
            for item in preflight.authorities
            if item.state not in {"upgrade_required", "current"}
        ]
        if invalid:
            raise SchemaMigrationError(
                f"Schema preflight failed: {invalid[0].database} "
                f"({invalid[0].detail})"
            )

        upgraded: list[str] = []
        already_current: list[str] = []
        for authority in AUTHORITIES:
            changed = self._upgrade_authority(
                authority,
                paths[authority.key],
            )
            if changed:
                upgraded.append(authority.key)
            else:
                already_current.append(authority.key)

        verified = self.verify(data_root=root)
        return SchemaUpgradeResult(
            backup_id=backup.backup_id,
            target_version=self.CURRENT_VERSION,
            upgraded=upgraded,
            already_current=already_current,
            authorities=verified.authorities,
        )

    def verify(
        self,
        *,
        data_root: str | Path | None = None,
    ) -> SchemaMigrationStatus:
        result = self.status(data_root=data_root)
        invalid = [
            item for item in result.authorities if item.state != "current"
        ]
        if invalid:
            raise SchemaMigrationError(
                f"Schema verification failed: {invalid[0].database} "
                f"({invalid[0].state})"
            )
        return result

    def assert_no_newer_versions(self) -> None:
        for authority in AUTHORITIES:
            path = authority.resolve_path()
            if not path.exists():
                continue
            self._ensure_database_file(path, authority.filename)
            try:
                with self._connect_readonly(path) as connection:
                    version = int(
                        connection.execute(
                            "PRAGMA user_version"
                        ).fetchone()[0]
                    )
            except sqlite3.DatabaseError as exc:
                raise SchemaMigrationError(
                    f"Runtime schema is invalid: {authority.filename}"
                ) from exc
            if version > self.CURRENT_VERSION:
                raise SchemaMigrationError(
                    f"Runtime schema is newer than this application: "
                    f"{authority.filename}"
                )

    def assert_runtime_compatible(self) -> SchemaMigrationStatus:
        result = self._status(
            full_integrity=False,
        )
        incompatible = [
            item
            for item in result.authorities
            if item.state
            not in {"current", "upgrade_required"}
        ]
        if incompatible:
            item = incompatible[0]
            raise SchemaMigrationError(
                f"Runtime schema is incompatible: {item.database} "
                f"({item.state})"
            )
        return result
