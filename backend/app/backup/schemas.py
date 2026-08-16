from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


BackupFileKind = Literal["sqlite", "faiss_index", "faiss_mapping"]


class BackupFileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(min_length=1, max_length=512)
    kind: BackupFileKind
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sqlite_user_version: int | None = Field(default=None, ge=0)
    sqlite_table_count: int | None = Field(default=None, ge=0)
    faiss_dimension: int | None = Field(default=None, gt=0)
    faiss_count: int | None = Field(default=None, ge=0)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("relative_path must use POSIX separators")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("relative_path must stay inside the backup")
        if path.as_posix() != value:
            raise ValueError("relative_path must be normalized")
        return value

    @model_validator(mode="after")
    def validate_kind_metadata(self) -> "BackupFileEntry":
        sqlite_metadata = (
            self.sqlite_user_version,
            self.sqlite_table_count,
        )
        faiss_metadata = (self.faiss_dimension, self.faiss_count)
        if self.kind == "sqlite" and any(
            value is None for value in sqlite_metadata
        ):
            raise ValueError("SQLite entries require schema metadata")
        if self.kind != "sqlite" and any(
            value is not None for value in sqlite_metadata
        ):
            raise ValueError("Only SQLite entries may have schema metadata")
        if self.kind == "faiss_index" and any(
            value is None for value in faiss_metadata
        ):
            raise ValueError("FAISS index entries require index metadata")
        if self.kind != "faiss_index" and any(
            value is not None for value in faiss_metadata
        ):
            raise ValueError("Only FAISS index entries may have index metadata")
        return self


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    backup_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    application_version: str = Field(min_length=1, max_length=128)
    created_at: datetime
    consistency_mode: Literal["offline_required"] = "offline_required"
    source_layout: Literal["novelforge-data-v1"] = "novelforge-data-v1"
    files: list[BackupFileEntry] = Field(min_length=1)
    rebuild_required: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_paths(self) -> "BackupManifest":
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Backup manifest contains duplicate paths")
        if len(self.rebuild_required) != len(set(self.rebuild_required)):
            raise ValueError("Backup manifest contains duplicate components")
        return self

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class BackupVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool = True
    backup_id: str
    checked_files: int = Field(ge=0)
    rebuild_required: list[str] = Field(default_factory=list)


class BackupRestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_id: str
    dry_run: bool
    restored_files: int = Field(ge=0)
    rebuild_required: list[str] = Field(default_factory=list)
