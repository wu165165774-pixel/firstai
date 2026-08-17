from __future__ import annotations

import hashlib
import inspect
import json
import re
import sys

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, get_args

from pydantic import ValidationError

from app.config.settings import settings
from app.plugins.schemas import (
    PluginCapability,
    PluginCatalogData,
    PluginCatalogItem,
    PluginManifest,
    PluginPermission,
)
from app.plugins.service import (
    MAX_MANIFEST_BYTES,
    PLUGIN_MANIFEST_NAME,
    PluginCatalogService,
    PluginConfigurationError,
    validate_plugin_configuration,
)


MAX_ENTRY_POINT_BYTES = 1024 * 1024
EXTENSION_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)
MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CleanupCallback = Callable[[], Any]


class PluginRuntimeError(RuntimeError):
    def __init__(self, code: str, plugin_id: str | None = None) -> None:
        self.code = code
        self.plugin_id = plugin_id
        super().__init__(f"Plugin runtime failed: {code}")


def configured_permission_grants(
    raw: str | None = None,
) -> dict[str, frozenset[str]]:
    source = settings.plugin_permission_grants_json if raw is None else raw
    try:
        value = json.loads(source)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PluginConfigurationError(
            "PLUGIN_PERMISSION_GRANTS_JSON must be a JSON object."
        ) from exc
    if not isinstance(value, dict):
        raise PluginConfigurationError(
            "PLUGIN_PERMISSION_GRANTS_JSON must be a JSON object."
        )
    allowed_permissions = set(get_args(PluginPermission))
    result: dict[str, frozenset[str]] = {}
    from app.plugins.schemas import PLUGIN_ID_PATTERN

    for raw_plugin_id, raw_permissions in value.items():
        plugin_id = str(raw_plugin_id or "").strip()
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginConfigurationError(
                "Plugin permission grants contain an invalid plugin ID."
            )
        if not isinstance(raw_permissions, list):
            raise PluginConfigurationError(
                "Each plugin permission grant must be a JSON array."
            )
        permissions = [str(item or "").strip() for item in raw_permissions]
        if (
            len(permissions) != len(set(permissions))
            or any(item not in allowed_permissions for item in permissions)
        ):
            raise PluginConfigurationError(
                "Plugin permission grants contain invalid permissions."
            )
        result[plugin_id] = frozenset(permissions)
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class PluginExtension:
    plugin_id: str
    capability: str
    extension_id: str
    value: Any


class PluginRuntimeContext:
    def __init__(
        self,
        manifest: PluginManifest,
        core_version: str,
        granted_permissions: frozenset[str],
    ) -> None:
        self.plugin_id = manifest.plugin_id
        self.plugin_version = manifest.version
        self.core_version = core_version
        self.capabilities = tuple(manifest.capabilities)
        self.granted_permissions = tuple(sorted(granted_permissions))
        self._extensions: list[PluginExtension] = []
        self._cleanups: list[CleanupCallback] = []
        self._sealed = False

    def register_extension(
        self,
        capability: PluginCapability,
        extension_id: str,
        value: Any,
    ) -> None:
        if self._sealed:
            raise PluginRuntimeError("activation_context_sealed", self.plugin_id)
        if capability not in self.capabilities:
            raise PluginRuntimeError(
                "capability_not_declared",
                self.plugin_id,
            )
        normalized = str(extension_id or "").strip()
        if (
            not EXTENSION_ID_PATTERN.fullmatch(normalized)
            or not normalized.startswith(f"{self.plugin_id}.")
        ):
            raise PluginRuntimeError(
                "extension_id_not_namespaced",
                self.plugin_id,
            )
        if value is None:
            raise PluginRuntimeError("extension_value_missing", self.plugin_id)
        key = (capability, normalized)
        if any(
            (item.capability, item.extension_id) == key
            for item in self._extensions
        ):
            raise PluginRuntimeError("duplicate_extension", self.plugin_id)
        self._extensions.append(
            PluginExtension(
                plugin_id=self.plugin_id,
                capability=capability,
                extension_id=normalized,
                value=value,
            )
        )

    def register_cleanup(self, callback: CleanupCallback) -> None:
        if self._sealed:
            raise PluginRuntimeError("activation_context_sealed", self.plugin_id)
        if not callable(callback):
            raise PluginRuntimeError("cleanup_not_callable", self.plugin_id)
        self._cleanups.append(callback)

    @property
    def staged_extensions(self) -> tuple[PluginExtension, ...]:
        return tuple(self._extensions)

    @property
    def cleanup_callbacks(self) -> tuple[CleanupCallback, ...]:
        return tuple(self._cleanups)

    def seal(self) -> None:
        self._sealed = True


@dataclass
class _ActivePlugin:
    plugin_id: str
    module_name: str
    module: ModuleType
    handle: Any
    context: PluginRuntimeContext


class PluginRuntimeManager:
    def __init__(
        self,
        catalog_service: PluginCatalogService,
        permission_grants_json: str | None = None,
    ) -> None:
        self.catalog_service = catalog_service
        self._permission_grants_json = permission_grants_json
        self._active: dict[str, _ActivePlugin] = {}
        self._activation_order: list[str] = []
        self._extensions: dict[str, dict[str, PluginExtension]] = {}
        self._failures: dict[str, str] = {}
        self._generation = 0

    def _grants(self) -> dict[str, frozenset[str]]:
        return configured_permission_grants(self._permission_grants_json)

    @staticmethod
    def _bounded_read(path: Path, limit: int, error_code: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise PluginRuntimeError(error_code)
        try:
            with path.open("rb") as stream:
                value = stream.read(limit + 1)
        except OSError as exc:
            raise PluginRuntimeError(error_code) from exc
        if len(value) > limit:
            raise PluginRuntimeError(error_code)
        return value

    def _verified_manifest(self, item: PluginCatalogItem) -> tuple[Path, PluginManifest]:
        if not item.plugin_id or not item.manifest_sha256:
            raise PluginRuntimeError("manifest_not_activatable", item.plugin_id)
        package_path = self.catalog_service.plugin_root / item.package
        if package_path.is_symlink() or not package_path.is_dir():
            raise PluginRuntimeError("unsafe_package_path", item.plugin_id)
        manifest_path = package_path / PLUGIN_MANIFEST_NAME
        raw = self._bounded_read(
            manifest_path,
            MAX_MANIFEST_BYTES,
            "manifest_changed",
        )
        if hashlib.sha256(raw).hexdigest() != item.manifest_sha256:
            raise PluginRuntimeError("manifest_changed", item.plugin_id)
        try:
            manifest = PluginManifest.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError, RecursionError) as exc:
            raise PluginRuntimeError("manifest_changed", item.plugin_id) from exc
        if manifest.plugin_id != item.plugin_id:
            raise PluginRuntimeError("manifest_changed", item.plugin_id)
        if manifest.manifest_version != 2 or manifest.integrity is None:
            raise PluginRuntimeError(
                "runtime_manifest_upgrade_required",
                item.plugin_id,
            )
        return package_path, manifest

    @staticmethod
    def _entry_point_path(
        package_path: Path,
        manifest: PluginManifest,
    ) -> tuple[Path, str]:
        module_name, attribute = manifest.entry_point.split(":", 1)
        if not MODULE_NAME_PATTERN.fullmatch(module_name):
            raise PluginRuntimeError(
                "runtime_entry_point_unsupported",
                manifest.plugin_id,
            )
        entry_path = package_path / f"{module_name}.py"
        try:
            resolved_package = package_path.resolve(strict=True)
            resolved_entry = entry_path.resolve(strict=True)
        except OSError as exc:
            raise PluginRuntimeError(
                "entry_point_missing",
                manifest.plugin_id,
            ) from exc
        if resolved_entry.parent != resolved_package or entry_path.is_symlink():
            raise PluginRuntimeError(
                "unsafe_entry_point_path",
                manifest.plugin_id,
            )
        return entry_path, attribute

    @staticmethod
    async def _invoke(callback: Callable[..., Any], *args: Any) -> Any:
        result = callback(*args)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _run_cleanups(self, context: PluginRuntimeContext) -> None:
        for callback in reversed(context.cleanup_callbacks):
            try:
                await self._invoke(callback)
            except BaseException:
                continue

    async def _rollback_candidate(
        self,
        handle: Any,
        context: PluginRuntimeContext,
    ) -> None:
        deactivate = getattr(handle, "deactivate", None) if handle is not None else None
        if deactivate is not None and callable(deactivate):
            try:
                await self._invoke(deactivate)
            except BaseException:
                pass
        await self._run_cleanups(context)

    def _commit_extensions(self, context: PluginRuntimeContext) -> None:
        for extension in context.staged_extensions:
            existing = self._extensions.get(extension.capability, {})
            if extension.extension_id in existing:
                raise PluginRuntimeError(
                    "duplicate_extension",
                    context.plugin_id,
                )
        for extension in context.staged_extensions:
            self._extensions.setdefault(extension.capability, {})[
                extension.extension_id
            ] = extension

    async def _activate_one(
        self,
        item: PluginCatalogItem,
        grants: dict[str, frozenset[str]],
    ) -> _ActivePlugin:
        package_path, manifest = self._verified_manifest(item)
        granted = grants.get(manifest.plugin_id, frozenset())
        if not set(manifest.permissions).issubset(granted):
            raise PluginRuntimeError(
                "permissions_not_granted",
                manifest.plugin_id,
            )
        entry_path, attribute = self._entry_point_path(package_path, manifest)
        source = self._bounded_read(
            entry_path,
            MAX_ENTRY_POINT_BYTES,
            "entry_point_unreadable",
        )
        expected_hash = manifest.integrity.entry_point_sha256
        if hashlib.sha256(source).hexdigest() != expected_hash:
            raise PluginRuntimeError(
                "entry_point_integrity_mismatch",
                manifest.plugin_id,
            )

        module_token = hashlib.sha256(
            f"{manifest.plugin_id}:{expected_hash}".encode("utf-8")
        ).hexdigest()[:24]
        module_name = f"_novelforge_plugin_{module_token}"
        module = ModuleType(module_name)
        module.__file__ = str(entry_path)
        module.__package__ = ""
        sys.modules[module_name] = module
        try:
            code = compile(source, str(entry_path), "exec")
            exec(code, module.__dict__)
            entry: Any = module
            for segment in attribute.split("."):
                entry = getattr(entry, segment)
            if not callable(entry):
                raise PluginRuntimeError(
                    "entry_point_not_callable",
                    manifest.plugin_id,
                )
        except PluginRuntimeError:
            sys.modules.pop(module_name, None)
            raise
        except BaseException as exc:
            sys.modules.pop(module_name, None)
            raise PluginRuntimeError(
                "entry_point_import_failed",
                manifest.plugin_id,
            ) from exc

        context = PluginRuntimeContext(
            manifest,
            self.catalog_service.core_version,
            granted,
        )
        handle: Any = None
        try:
            handle = await self._invoke(entry, context)
            context.seal()
            deactivate = getattr(handle, "deactivate", None) if handle is not None else None
            if deactivate is not None and not callable(deactivate):
                raise PluginRuntimeError(
                    "deactivate_not_callable",
                    manifest.plugin_id,
                )
            self._commit_extensions(context)
        except PluginRuntimeError:
            await self._rollback_candidate(handle, context)
            sys.modules.pop(module_name, None)
            raise
        except BaseException as exc:
            await self._rollback_candidate(handle, context)
            sys.modules.pop(module_name, None)
            raise PluginRuntimeError(
                "activation_failed",
                manifest.plugin_id,
            ) from exc
        return _ActivePlugin(
            plugin_id=manifest.plugin_id,
            module_name=module_name,
            module=module,
            handle=handle,
            context=context,
        )

    async def activate_enabled(self) -> PluginCatalogData:
        configured_permission_grants(self._permission_grants_json)
        catalog = validate_plugin_configuration(self.catalog_service)
        self._failures.clear()
        if not self.catalog_service.execution_enabled:
            if self._active:
                await self.deactivate_all()
            return self.catalog()
        if self._active:
            return self.catalog()
        grants = self._grants()
        enabled_items = [item for item in catalog.plugins if item.enabled]
        for item in enabled_items:
            try:
                active = await self._activate_one(item, grants)
            except PluginRuntimeError as exc:
                plugin_id = exc.plugin_id or item.plugin_id or item.package
                self._failures[plugin_id] = exc.code
                await self.deactivate_all(clear_failures=False)
                raise
            self._active[active.plugin_id] = active
            self._activation_order.append(active.plugin_id)
        self._generation += 1
        return self.catalog()

    async def deactivate_all(self, *, clear_failures: bool = True) -> None:
        if clear_failures:
            self._failures.clear()
        for plugin_id in reversed(self._activation_order):
            active = self._active.get(plugin_id)
            if active is None:
                continue
            deactivate = (
                getattr(active.handle, "deactivate", None)
                if active.handle is not None
                else None
            )
            if deactivate is not None and callable(deactivate):
                try:
                    await self._invoke(deactivate)
                except BaseException:
                    self._failures[plugin_id] = "deactivation_failed"
            await self._run_cleanups(active.context)
            for extension in active.context.staged_extensions:
                capability_items = self._extensions.get(extension.capability, {})
                capability_items.pop(extension.extension_id, None)
                if not capability_items:
                    self._extensions.pop(extension.capability, None)
            sys.modules.pop(active.module_name, None)
            self._active.pop(plugin_id, None)
        self._activation_order.clear()
        self._generation += 1

    def extensions(self, capability: PluginCapability) -> dict[str, Any]:
        return {
            extension_id: extension.value
            for extension_id, extension in sorted(
                self._extensions.get(capability, {}).items()
            )
        }

    def catalog(self) -> PluginCatalogData:
        catalog = self.catalog_service.catalog()
        items: list[PluginCatalogItem] = []
        for item in catalog.plugins:
            if item.plugin_id in self._active:
                item = item.model_copy(
                    update={
                        "state": "enabled",
                        "loaded": True,
                        "activation_allowed": True,
                        "error_code": None,
                    }
                )
            elif item.plugin_id in self._failures:
                item = item.model_copy(
                    update={
                        "state": "failed",
                        "loaded": False,
                        "activation_allowed": False,
                        "error_code": self._failures[item.plugin_id],
                    }
                )
            items.append(item)
        return catalog.model_copy(
            update={
                "active_plugins": list(self._activation_order),
                "runtime_generation": self._generation,
                "plugins": items,
            }
        )
