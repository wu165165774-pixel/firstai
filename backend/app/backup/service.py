from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath

import faiss

from pydantic import ValidationError

from app.version import APP_VERSION

from .schemas import (
    BackupFileEntry,
    BackupManifest,
    BackupRestoreResult,
    BackupVerification,
)


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupCreateResult:
    backup_dir: Path
    manifest: BackupManifest
    verification: BackupVerification


class BackupService:
    """Create and restore snapshots during an offline maintenance window."""

    SQLITE_FILES = (
        "novels.db",
        "workflow_runs.db",
        "memory.db",
        "external_knowledge.db",
        "temporal_graph.db",
    )
    FAISS_PAIRS = {
        "memory_vector": (
            "vector_db/memory.index",
            "vector_db/memory_ids.json",
        ),
        "external_knowledge_vector": (
            "vector_db/external_knowledge.index",
            "vector_db/external_knowledge_ids.json",
        ),
    }
    FAISS_FILES = tuple(
        path for pair in FAISS_PAIRS.values() for path in pair
    )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _ensure_regular_file(path: Path, *, label: str) -> None:
        if path.is_symlink() or not path.is_file():
            raise BackupError(f"{label} must be a regular file: {path.name}")

    @staticmethod
    def _safe_child(root: Path, relative_path: str) -> Path:
        current = root
        for part in PurePosixPath(relative_path).parts:
            current = current / part
            if current.is_symlink():
                raise BackupError(
                    f"Symbolic links are not allowed: {relative_path}"
                )
        resolved_root = root.resolve()
        resolved = current.resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise BackupError(f"Path escapes its data root: {relative_path}")
        return current

    @staticmethod
    def _sqlite_metadata(path: Path) -> tuple[int, int]:
        try:
            with sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro",
                uri=True,
            ) as conn:
                integrity = [
                    str(row[0])
                    for row in conn.execute("PRAGMA integrity_check")
                ]
                if integrity != ["ok"]:
                    raise BackupError(
                        f"SQLite integrity check failed: {path.name}"
                    )
                user_version = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                table_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchone()[0]
                )
                return user_version, table_count
        except sqlite3.DatabaseError as exc:
            raise BackupError(
                f"Invalid SQLite backup file: {path.name}"
            ) from exc

    @staticmethod
    def _mapping_count(path: Path) -> int:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BackupError(f"Invalid FAISS mapping: {path.name}") from exc
        if not isinstance(value, dict):
            raise BackupError(f"Invalid FAISS mapping: {path.name}")
        return len(value)

    @staticmethod
    def _faiss_metadata(path: Path) -> tuple[int, int]:
        try:
            index = faiss.read_index(str(path))
        except (OSError, RuntimeError) as exc:
            raise BackupError(f"Invalid FAISS index: {path.name}") from exc
        dimension = int(index.d)
        count = int(index.ntotal)
        if dimension <= 0 or count < 0:
            raise BackupError(f"Invalid FAISS index: {path.name}")
        return dimension, count

    @staticmethod
    def _component_for_sqlite(name: str) -> str:
        return name.removesuffix(".db")

    @staticmethod
    def _safe_backup_id(backup_id: str | None) -> str:
        if backup_id is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_id = f"novelforge-{timestamp}-{uuid.uuid4().hex[:8]}"
        try:
            BackupManifest(
                backup_id=backup_id,
                application_version=APP_VERSION,
                created_at=datetime.now(timezone.utc),
                files=[
                    BackupFileEntry(
                        component="validation",
                        relative_path="validation.db",
                        kind="sqlite",
                        size_bytes=0,
                        sha256="0" * 64,
                        sqlite_user_version=0,
                        sqlite_table_count=0,
                    )
                ],
            )
        except ValidationError as exc:
            raise BackupError("Invalid backup_id.") from exc
        return backup_id

    def _backup_sqlite(self, source: Path, target: Path) -> None:
        self._ensure_regular_file(source, label="SQLite source")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(
                f"file:{source.as_posix()}?mode=ro",
                uri=True,
                timeout=30.0,
            ) as source_conn, sqlite3.connect(target) as target_conn:
                source_conn.backup(target_conn)
        except sqlite3.DatabaseError as exc:
            raise BackupError(
                f"SQLite backup failed: {source.name}"
            ) from exc

    @staticmethod
    def _finalize_directory(temporary: Path, final: Path) -> None:
        try:
            os.replace(temporary, final)
            return
        except OSError:
            pass

        created_final = False
        try:
            final.mkdir()
            created_final = True
            shutil.copytree(temporary / "files", final / "files")
            shutil.copy2(
                temporary / "manifest.json",
                final / "manifest.json",
            )
        except FileExistsError as exc:
            raise BackupError("Backup target already exists.") from exc
        except (OSError, shutil.Error) as exc:
            if created_final and final.exists():
                shutil.rmtree(final, ignore_errors=True)
            raise BackupError("Backup finalization failed.") from exc
        finally:
            if created_final and final.is_dir():
                shutil.rmtree(temporary, ignore_errors=True)

    def create(
        self,
        *,
        data_root: str | Path,
        output_root: str | Path,
        backup_id: str | None = None,
        offline_confirmed: bool = False,
    ) -> BackupCreateResult:
        if not offline_confirmed:
            raise BackupError(
                "Offline maintenance must be explicitly confirmed."
            )

        raw_data = Path(data_root).expanduser()
        if raw_data.is_symlink():
            raise BackupError("Data root must not be a symbolic link.")
        data = raw_data.resolve()
        if not data.is_dir():
            raise BackupError("Data root must be an existing regular directory.")

        raw_output = Path(output_root).expanduser()
        if raw_output.is_symlink():
            raise BackupError("Output root must not be a symbolic link.")
        output = raw_output.resolve()
        if output.exists() and not output.is_dir():
            raise BackupError("Output root must be a regular directory.")
        output.mkdir(parents=True, exist_ok=True)

        resolved_id = self._safe_backup_id(backup_id)
        final_dir = output / resolved_id
        if final_dir.exists():
            raise BackupError("Backup target already exists.")

        temporary_dir = output / f".{resolved_id}.tmp-{uuid.uuid4().hex}"
        files_root = temporary_dir / "files"
        entries: list[BackupFileEntry] = []
        rebuild_required: list[str] = []
        finalized = False

        try:
            files_root.mkdir(parents=True)
            for relative_path in self.SQLITE_FILES:
                source = self._safe_child(data, relative_path)
                if not source.exists():
                    raise BackupError(
                        f"Required SQLite authority is missing: {relative_path}"
                    )
                target = files_root / relative_path
                self._backup_sqlite(source, target)
                user_version, table_count = self._sqlite_metadata(target)
                entries.append(
                    BackupFileEntry(
                        component=self._component_for_sqlite(relative_path),
                        relative_path=relative_path,
                        kind="sqlite",
                        size_bytes=target.stat().st_size,
                        sha256=self._sha256(target),
                        sqlite_user_version=user_version,
                        sqlite_table_count=table_count,
                    )
                )

            for component, pair in self.FAISS_PAIRS.items():
                sources = [
                    self._safe_child(data, relative_path)
                    for relative_path in pair
                ]
                present = [path.exists() for path in sources]
                if present == [False, False]:
                    rebuild_required.append(component)
                    continue
                if not all(present):
                    raise BackupError(
                        f"Found incomplete FAISS pair: {component}"
                    )
                targets: list[Path] = []
                for relative_path, source in zip(pair, sources, strict=True):
                    self._ensure_regular_file(source, label="FAISS source")
                    target = files_root / relative_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    targets.append(target)
                dimension, vector_count = self._faiss_metadata(targets[0])
                mapping_count = self._mapping_count(targets[1])
                if vector_count != mapping_count:
                    raise BackupError(
                        "FAISS vector count does not match mapping: "
                        f"{component}"
                    )
                entries.extend(
                    [
                        BackupFileEntry(
                            component=component,
                            relative_path=pair[0],
                            kind="faiss_index",
                            size_bytes=targets[0].stat().st_size,
                            sha256=self._sha256(targets[0]),
                            faiss_dimension=dimension,
                            faiss_count=vector_count,
                        ),
                        BackupFileEntry(
                            component=component,
                            relative_path=pair[1],
                            kind="faiss_mapping",
                            size_bytes=targets[1].stat().st_size,
                            sha256=self._sha256(targets[1]),
                        ),
                    ]
                )

            manifest = BackupManifest(
                backup_id=resolved_id,
                application_version=APP_VERSION,
                created_at=datetime.now(timezone.utc),
                files=entries,
                rebuild_required=sorted(rebuild_required),
            )
            (temporary_dir / "manifest.json").write_text(
                manifest.model_dump_json(indent=2),
                encoding="utf-8",
            )
            self._finalize_directory(temporary_dir, final_dir)
            finalized = True
            verification = self.verify(final_dir)
            return BackupCreateResult(
                backup_dir=final_dir,
                manifest=manifest,
                verification=verification,
            )
        except Exception:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)
            if finalized and final_dir.exists():
                shutil.rmtree(final_dir)
            raise

    @staticmethod
    def _load_manifest(backup_dir: Path) -> BackupManifest:
        manifest_path = backup_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise BackupError("Backup manifest is missing or invalid.")
        try:
            return BackupManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError) as exc:
            raise BackupError("Backup manifest is invalid.") from exc

    def _validate_manifest_layout(self, manifest: BackupManifest) -> None:
        listed = {item.relative_path for item in manifest.files}
        allowed = set(self.SQLITE_FILES) | set(self.FAISS_FILES)
        unknown = sorted(listed - allowed)
        if unknown:
            raise BackupError(
                f"Backup manifest contains an unknown file: {unknown[0]}"
            )
        missing_sqlite = sorted(set(self.SQLITE_FILES) - listed)
        if missing_sqlite:
            raise BackupError(
                "Backup manifest is missing a SQLite authority: "
                f"{missing_sqlite[0]}"
            )

        rebuild = set(manifest.rebuild_required)
        unknown_rebuild = sorted(rebuild - set(self.FAISS_PAIRS))
        if unknown_rebuild:
            raise BackupError(
                "Backup manifest has an unknown rebuild component: "
                f"{unknown_rebuild[0]}"
            )
        for component, pair in self.FAISS_PAIRS.items():
            present = [relative_path in listed for relative_path in pair]
            if any(present) and not all(present):
                raise BackupError(
                    f"Backup manifest has an incomplete FAISS pair: {component}"
                )
            if all(present) == (component in rebuild):
                raise BackupError(
                    f"Backup manifest has invalid rebuild state: {component}"
                )

    def verify(self, backup_dir: str | Path) -> BackupVerification:
        raw_backup = Path(backup_dir).expanduser()
        if raw_backup.is_symlink():
            raise BackupError("Backup directory must not be a symbolic link.")
        backup = raw_backup.resolve()
        if not backup.is_dir():
            raise BackupError("Backup directory does not exist.")
        manifest = self._load_manifest(backup)
        self._validate_manifest_layout(manifest)
        files_root = backup / "files"
        if files_root.is_symlink() or not files_root.is_dir():
            raise BackupError("Backup files directory is missing or invalid.")

        expected: set[str] = set()
        for entry in manifest.files:
            expected.add(entry.relative_path)
            path = self._safe_child(files_root, entry.relative_path)
            self._ensure_regular_file(path, label="Backup entry")
            if path.stat().st_size != entry.size_bytes:
                raise BackupError(
                    f"Backup size mismatch: {entry.relative_path}"
                )
            if self._sha256(path) != entry.sha256:
                raise BackupError(
                    f"Backup checksum mismatch: {entry.relative_path}"
                )
            if entry.kind == "sqlite":
                user_version, table_count = self._sqlite_metadata(path)
                if (
                    user_version != entry.sqlite_user_version
                    or table_count != entry.sqlite_table_count
                ):
                    raise BackupError(
                        f"SQLite metadata mismatch: {entry.relative_path}"
                    )
            elif entry.kind == "faiss_index":
                dimension, count = self._faiss_metadata(path)
                if (
                    dimension != entry.faiss_dimension
                    or count != entry.faiss_count
                ):
                    raise BackupError(
                        f"FAISS metadata mismatch: {entry.relative_path}"
                    )
            elif entry.kind == "faiss_mapping":
                self._mapping_count(path)

        entries_by_path = {
            item.relative_path: item for item in manifest.files
        }
        for component, pair in self.FAISS_PAIRS.items():
            if component in manifest.rebuild_required:
                continue
            index_entry = entries_by_path[pair[0]]
            mapping_count = self._mapping_count(
                self._safe_child(files_root, pair[1])
            )
            if index_entry.faiss_count != mapping_count:
                raise BackupError(
                    "FAISS vector count does not match mapping: "
                    f"{component}"
                )

        actual: set[str] = set()
        for path in files_root.rglob("*"):
            if path.is_symlink():
                raise BackupError("Backup contains a symbolic link.")
            if path.is_file():
                actual.add(path.relative_to(files_root).as_posix())
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        if extra:
            raise BackupError(f"Backup contains unmanifested files: {extra[0]}")
        if missing:
            raise BackupError(f"Backup files are missing: {missing[0]}")

        return BackupVerification(
            backup_id=manifest.backup_id,
            checked_files=len(manifest.files),
            rebuild_required=manifest.rebuild_required,
        )

    def restore(
        self,
        *,
        backup_dir: str | Path,
        target_root: str | Path,
        execute: bool = False,
    ) -> BackupRestoreResult:
        backup = Path(backup_dir).expanduser().resolve()
        verification = self.verify(backup)
        manifest = self._load_manifest(backup)
        target = Path(target_root).expanduser().resolve()

        if target.exists():
            raise BackupError("Restore target must not exist.")
        if target == backup or backup in target.parents:
            raise BackupError("Restore target must be outside the backup.")
        if not execute:
            return BackupRestoreResult(
                backup_id=manifest.backup_id,
                dry_run=True,
                restored_files=0,
                rebuild_required=manifest.rebuild_required,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}"
        try:
            staging.mkdir()
            for entry in manifest.files:
                source = self._safe_child(
                    backup / "files",
                    entry.relative_path,
                )
                destination = staging.joinpath(
                    *PurePosixPath(entry.relative_path).parts
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if self._sha256(destination) != entry.sha256:
                    raise BackupError(
                        f"Restored checksum mismatch: {entry.relative_path}"
                    )
            os.replace(staging, target)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

        return BackupRestoreResult(
            backup_id=manifest.backup_id,
            dry_run=False,
            restored_files=verification.checked_files,
            rebuild_required=manifest.rebuild_required,
        )
