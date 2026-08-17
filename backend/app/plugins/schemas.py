from __future__ import annotations

import re

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.plugins.versioning import parse_semantic_version


PLUGIN_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)
ENTRY_POINT_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$"
)

PluginCapability = Literal[
    "agent",
    "exporter",
    "frontend",
    "llm_provider",
    "prompt",
    "retrieval",
]
PluginPermission = Literal[
    "database_read",
    "database_write",
    "filesystem_read",
    "filesystem_write",
    "model_access",
    "network",
]
PluginState = Literal[
    "disabled",
    "enabled",
    "failed",
    "incompatible",
    "invalid",
]


class PluginIntegrity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_point_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("entry_point_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("entry_point_sha256 must be hexadecimal")
        return normalized


class PluginCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_api: int = Field(ge=1)
    min_core_version: str = Field(min_length=1, max_length=64)
    max_core_version_exclusive: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )

    @field_validator("min_core_version", "max_core_version_exclusive")
    @classmethod
    def validate_version_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        parse_semantic_version(normalized)
        return normalized

    @model_validator(mode="after")
    def validate_version_window(self) -> "PluginCompatibility":
        if self.max_core_version_exclusive is None:
            return self
        minimum = parse_semantic_version(self.min_core_version)
        maximum = parse_semantic_version(self.max_core_version_exclusive)
        if not minimum < maximum:
            raise ValueError(
                "max_core_version_exclusive must be greater than min_core_version"
            )
        return self


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: Literal[1, 2]
    plugin_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    entry_point: str = Field(min_length=3, max_length=256)
    capabilities: list[PluginCapability] = Field(min_length=1, max_length=20)
    permissions: list[PluginPermission] = Field(default_factory=list, max_length=20)
    requires: PluginCompatibility
    integrity: PluginIntegrity | None = None

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, value: str) -> str:
        normalized = value.strip()
        if not PLUGIN_ID_PATTERN.fullmatch(normalized):
            raise ValueError("plugin_id is invalid")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized = value.strip()
        parse_semantic_version(normalized)
        return normalized

    @field_validator("entry_point")
    @classmethod
    def validate_entry_point(cls, value: str) -> str:
        normalized = value.strip()
        if not ENTRY_POINT_PATTERN.fullmatch(normalized):
            raise ValueError("entry_point is invalid")
        return normalized

    @field_validator("capabilities", "permissions")
    @classmethod
    def reject_duplicates(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate declarations are not allowed")
        return value

    @model_validator(mode="after")
    def validate_manifest_generation(self) -> "PluginManifest":
        if self.manifest_version == 2 and self.integrity is None:
            raise ValueError("Manifest v2 requires integrity metadata")
        if self.manifest_version == 1 and self.integrity is not None:
            raise ValueError("Manifest v1 must not declare v2 integrity metadata")
        return self


class PluginCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package: str
    plugin_id: str | None = None
    manifest_version: int | None = None
    name: str | None = None
    version: str | None = None
    state: PluginState
    enabled: bool = False
    compatible: bool = False
    activation_allowed: bool = False
    loaded: bool = False
    capabilities: list[PluginCapability] = Field(default_factory=list)
    permissions: list[PluginPermission] = Field(default_factory=list)
    entry_point: str | None = None
    manifest_sha256: str | None = None
    error_code: str | None = None


class PluginCatalogData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_api_version: int
    core_version: str
    execution_enabled: bool = False
    root_available: bool
    configuration_valid: bool
    configured_enabled: list[str] = Field(default_factory=list)
    unknown_enabled: list[str] = Field(default_factory=list)
    active_plugins: list[str] = Field(default_factory=list)
    runtime_generation: int = 0
    plugins: list[PluginCatalogItem] = Field(default_factory=list)


class PluginCatalogResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: PluginCatalogData
