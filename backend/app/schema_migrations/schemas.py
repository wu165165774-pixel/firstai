from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthorityMigrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    authority: str
    database: str
    current_version: int = Field(ge=0)
    target_version: int = Field(ge=1)
    state: Literal[
        "upgrade_required",
        "current",
        "schema_incomplete",
        "unsupported_newer",
        "missing",
    ]
    contract_valid: bool
    ledger_valid: bool
    detail: str | None = None


class SchemaMigrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_version: int = Field(ge=1)
    authorities: list[AuthorityMigrationStatus]
    ready: bool


class SchemaUpgradeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_id: str
    target_version: int = Field(ge=1)
    upgraded: list[str]
    already_current: list[str]
    authorities: list[AuthorityMigrationStatus]
