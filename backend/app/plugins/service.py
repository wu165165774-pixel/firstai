from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config.settings import settings
from app.plugins.schemas import (
    PLUGIN_ID_PATTERN,
    PluginCatalogData,
    PluginCatalogItem,
    PluginManifest,
)
from app.plugins.versioning import parse_semantic_version
from app.version import APP_VERSION


PLUGIN_API_VERSION = 1
PLUGIN_MANIFEST_NAME = "novelforge-plugin.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PLUGIN_PACKAGES = 100
PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PluginConfigurationError(ValueError):
    pass


def configured_plugin_ids(raw: str | None = None) -> tuple[str, ...]:
    source = settings.plugin_enabled_json if raw is None else raw
    try:
        value = json.loads(source)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PluginConfigurationError(
            "PLUGIN_ENABLED_JSON must be a JSON array."
        ) from exc
    if not isinstance(value, list):
        raise PluginConfigurationError(
            "PLUGIN_ENABLED_JSON must be a JSON array."
        )
    normalized: list[str] = []
    for item in value:
        plugin_id = str(item or "").strip()
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginConfigurationError(
                "PLUGIN_ENABLED_JSON contains an invalid plugin ID."
            )
        if plugin_id in normalized:
            raise PluginConfigurationError(
                "PLUGIN_ENABLED_JSON contains a duplicate plugin ID."
            )
        normalized.append(plugin_id)
    return tuple(sorted(normalized))


class PluginCatalogService:
    def __init__(
        self,
        plugin_root: str | Path | None = None,
        enabled_json: str | None = None,
        core_version: str = APP_VERSION,
        execution_enabled: bool | None = None,
    ) -> None:
        self._plugin_root = Path(plugin_root) if plugin_root is not None else None
        self._enabled_json = enabled_json
        self._execution_enabled = execution_enabled
        self.core_version = core_version
        parse_semantic_version(core_version)

    @property
    def plugin_root(self) -> Path:
        if self._plugin_root is not None:
            return self._plugin_root
        return Path(settings.plugin_root)

    def _enabled(self) -> tuple[str, ...]:
        return configured_plugin_ids(self._enabled_json)

    @property
    def execution_enabled(self) -> bool:
        if self._execution_enabled is not None:
            return self._execution_enabled
        return bool(settings.plugin_execution_enabled)

    @staticmethod
    def _safe_candidate_id(value: Any) -> str | None:
        candidate = str(value or "").strip()
        if PLUGIN_ID_PATTERN.fullmatch(candidate):
            return candidate
        return None

    @staticmethod
    def _invalid(
        package: str,
        error_code: str,
        *,
        plugin_id: str | None = None,
        enabled: bool = False,
        manifest_sha256: str | None = None,
    ) -> PluginCatalogItem:
        return PluginCatalogItem(
            package=package,
            plugin_id=plugin_id,
            state="invalid",
            enabled=enabled,
            compatible=False,
            activation_allowed=False,
            loaded=False,
            manifest_sha256=manifest_sha256,
            error_code=error_code,
        )

    def _compatibility_error(self, manifest: PluginManifest) -> str | None:
        if manifest.requires.plugin_api != PLUGIN_API_VERSION:
            return "plugin_api_incompatible"
        core = parse_semantic_version(self.core_version)
        minimum = parse_semantic_version(manifest.requires.min_core_version)
        if core < minimum:
            return "core_version_too_old"
        maximum_text = manifest.requires.max_core_version_exclusive
        if maximum_text is not None:
            maximum = parse_semantic_version(maximum_text)
            if not core < maximum:
                return "core_version_too_new"
        return None

    def _read_package(
        self,
        package_path: Path,
        enabled_ids: set[str],
    ) -> PluginCatalogItem:
        package = package_path.name[:128]
        if not PACKAGE_NAME_PATTERN.fullmatch(package_path.name):
            return self._invalid(package, "invalid_package_name")
        if package_path.is_symlink():
            return self._invalid(package, "unsafe_package_link")
        manifest_path = package_path / PLUGIN_MANIFEST_NAME
        if manifest_path.is_symlink():
            return self._invalid(package, "unsafe_manifest_link")
        if not manifest_path.is_file():
            return self._invalid(package, "manifest_missing")
        try:
            with manifest_path.open("rb") as stream:
                raw = stream.read(MAX_MANIFEST_BYTES + 1)
        except OSError:
            return self._invalid(package, "manifest_unreadable")
        if len(raw) > MAX_MANIFEST_BYTES:
            return self._invalid(package, "manifest_too_large")
        digest = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return self._invalid(
                package,
                "manifest_invalid_json",
                manifest_sha256=digest,
            )
        candidate_id = (
            self._safe_candidate_id(payload.get("plugin_id"))
            if isinstance(payload, dict)
            else None
        )
        enabled = candidate_id in enabled_ids if candidate_id else False
        try:
            manifest = PluginManifest.model_validate(payload)
        except (ValidationError, RecursionError, TypeError, ValueError):
            return self._invalid(
                package,
                "manifest_invalid",
                plugin_id=candidate_id,
                enabled=enabled,
                manifest_sha256=digest,
            )
        compatibility_error = self._compatibility_error(manifest)
        compatible = compatibility_error is None
        enabled = manifest.plugin_id in enabled_ids
        if compatibility_error is not None:
            state = "incompatible"
        elif enabled:
            state = "enabled"
        else:
            state = "disabled"
        return PluginCatalogItem(
            package=package,
            plugin_id=manifest.plugin_id,
            manifest_version=manifest.manifest_version,
            name=manifest.name,
            version=manifest.version,
            state=state,
            enabled=enabled,
            compatible=compatible,
            activation_allowed=enabled and compatible,
            loaded=False,
            capabilities=manifest.capabilities,
            permissions=manifest.permissions,
            entry_point=manifest.entry_point,
            manifest_sha256=digest,
            error_code=compatibility_error,
        )

    def catalog(self) -> PluginCatalogData:
        enabled = self._enabled()
        enabled_ids = set(enabled)
        root = self.plugin_root
        if not root.is_dir():
            return PluginCatalogData(
                plugin_api_version=PLUGIN_API_VERSION,
                core_version=self.core_version,
                execution_enabled=self.execution_enabled,
                root_available=False,
                configuration_valid=not enabled,
                configured_enabled=list(enabled),
                unknown_enabled=list(enabled),
            )
        try:
            packages = sorted(
                (
                    item
                    for item in root.iterdir()
                    if item.is_symlink() or item.is_dir()
                ),
                key=lambda item: item.name,
            )
        except OSError:
            packages = []
            root_available = False
        else:
            root_available = True
        package_limit_exceeded = len(packages) > MAX_PLUGIN_PACKAGES
        if package_limit_exceeded:
            packages = packages[:MAX_PLUGIN_PACKAGES]
        items = [self._read_package(path, enabled_ids) for path in packages]

        counts: dict[str, int] = {}
        for item in items:
            if item.plugin_id:
                counts[item.plugin_id] = counts.get(item.plugin_id, 0) + 1
        duplicates = {plugin_id for plugin_id, count in counts.items() if count > 1}
        if duplicates:
            items = [
                item.model_copy(
                    update={
                        "state": "invalid",
                        "compatible": False,
                        "activation_allowed": False,
                        "error_code": "duplicate_plugin_id",
                    }
                )
                if item.plugin_id in duplicates
                else item
                for item in items
            ]

        discovered_ids = {item.plugin_id for item in items if item.plugin_id}
        unknown = sorted(enabled_ids - discovered_ids)
        enabled_invalid = any(
            item.enabled and not item.activation_allowed for item in items
        )
        configuration_valid = (
            root_available
            and not unknown
            and not enabled_invalid
            and not package_limit_exceeded
        )
        return PluginCatalogData(
            plugin_api_version=PLUGIN_API_VERSION,
            core_version=self.core_version,
            execution_enabled=self.execution_enabled,
            root_available=root_available,
            configuration_valid=configuration_valid,
            configured_enabled=list(enabled),
            unknown_enabled=unknown,
            plugins=items,
        )


def validate_plugin_configuration(
    service: PluginCatalogService | None = None,
) -> PluginCatalogData:
    catalog = (service or PluginCatalogService()).catalog()
    if not catalog.configuration_valid:
        raise PluginConfigurationError(
            "Enabled plugin configuration is missing, invalid, or incompatible."
        )
    return catalog
