import asyncio
import hashlib
import json
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.plugins.runtime import (
    PluginRuntimeError,
    PluginRuntimeManager,
    configured_permission_grants,
)
from app.plugins.service import PluginCatalogService, PluginConfigurationError
from app.version import APP_VERSION


class PluginRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_plugin(
        self,
        package: str,
        plugin_id: str,
        source: str,
        *,
        manifest_version: int = 2,
        capabilities: list[str] | None = None,
        permissions: list[str] | None = None,
        entry_point: str = "plugin:activate",
        source_hash: str | None = None,
    ) -> None:
        directory = self.root / package
        directory.mkdir()
        source_bytes = source.encode("utf-8")
        (directory / "plugin.py").write_bytes(source_bytes)
        payload = {
            "manifest_version": manifest_version,
            "plugin_id": plugin_id,
            "name": f"Runtime {plugin_id}",
            "version": "1.0.0",
            "entry_point": entry_point,
            "capabilities": capabilities or ["prompt"],
            "permissions": permissions or [],
            "requires": {
                "plugin_api": 1,
                "min_core_version": APP_VERSION,
                "max_core_version_exclusive": "2.0.0",
            },
        }
        if manifest_version == 2:
            payload["integrity"] = {
                "entry_point_sha256": source_hash
                or hashlib.sha256(source_bytes).hexdigest(),
            }
        (directory / "novelforge-plugin.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def manager(
        self,
        enabled: list[str],
        *,
        grants: dict[str, list[str]] | None = None,
        execution_enabled: bool = True,
    ) -> PluginRuntimeManager:
        service = PluginCatalogService(
            plugin_root=self.root,
            enabled_json=json.dumps(enabled),
            execution_enabled=execution_enabled,
        )
        return PluginRuntimeManager(
            service,
            permission_grants_json=json.dumps(grants or {}),
        )

    async def test_v2_plugin_activates_extensions_and_deactivates_cleanly(self) -> None:
        self.write_plugin(
            "sample",
            "sample.plugin",
            """
class Handle:
    async def deactivate(self):
        return None

async def activate(context):
    context.register_extension(
        "prompt",
        "sample.plugin.prompt",
        context,
    )
    return Handle()
""".strip()
            + "\n",
        )
        manager = self.manager(["sample.plugin"])
        catalog = await manager.activate_enabled()
        self.assertEqual(catalog.active_plugins, ["sample.plugin"])
        self.assertTrue(catalog.plugins[0].loaded)
        extension_context = manager.extensions("prompt")["sample.plugin.prompt"]
        self.assertEqual(extension_context.plugin_id, "sample.plugin")
        with self.assertRaisesRegex(
            PluginRuntimeError,
            "activation_context_sealed",
        ):
            extension_context.register_cleanup(lambda: None)
        await manager.deactivate_all()
        self.assertEqual(manager.extensions("prompt"), {})
        self.assertEqual(manager.catalog().active_plugins, [])

    async def test_execution_disabled_never_imports_entry_point(self) -> None:
        marker = self.root / "imported.txt"
        self.write_plugin(
            "disabled",
            "disabled.plugin",
            f"""
from pathlib import Path
Path({str(marker)!r}).write_text("imported")
def activate(context):
    return None
""".strip()
            + "\n",
        )
        manager = self.manager(
            ["disabled.plugin"],
            execution_enabled=False,
        )
        catalog = await manager.activate_enabled()
        self.assertFalse(catalog.execution_enabled)
        self.assertEqual(catalog.active_plugins, [])
        self.assertFalse(marker.exists())

    async def test_manifest_v1_is_catalog_only_at_runtime(self) -> None:
        self.write_plugin(
            "legacy",
            "legacy.plugin",
            "def activate(context):\n    return None\n",
            manifest_version=1,
        )
        manager = self.manager(["legacy.plugin"])
        with self.assertRaisesRegex(
            PluginRuntimeError,
            "runtime_manifest_upgrade_required",
        ):
            await manager.activate_enabled()
        item = manager.catalog().plugins[0]
        self.assertEqual(item.state, "failed")
        self.assertEqual(item.error_code, "runtime_manifest_upgrade_required")

    async def test_entry_point_integrity_mismatch_fails_before_import(self) -> None:
        marker = self.root / "integrity-imported.txt"
        self.write_plugin(
            "changed",
            "changed.plugin",
            f"""
from pathlib import Path
Path({str(marker)!r}).write_text("bad")
def activate(context):
    return None
""".strip()
            + "\n",
            source_hash="0" * 64,
        )
        manager = self.manager(["changed.plugin"])
        with self.assertRaisesRegex(
            PluginRuntimeError,
            "entry_point_integrity_mismatch",
        ):
            await manager.activate_enabled()
        self.assertFalse(marker.exists())

    async def test_declared_permissions_require_explicit_grants(self) -> None:
        self.write_plugin(
            "networked",
            "networked.plugin",
            "def activate(context):\n    return None\n",
            permissions=["network", "model_access"],
        )
        denied = self.manager(
            ["networked.plugin"],
            grants={"networked.plugin": ["network"]},
        )
        with self.assertRaisesRegex(
            PluginRuntimeError,
            "permissions_not_granted",
        ):
            await denied.activate_enabled()

        allowed = self.manager(
            ["networked.plugin"],
            grants={"networked.plugin": ["network", "model_access"]},
        )
        catalog = await allowed.activate_enabled()
        self.assertEqual(catalog.active_plugins, ["networked.plugin"])
        await allowed.deactivate_all()

    async def test_undeclared_capability_rolls_back_registered_cleanup(self) -> None:
        marker = self.root / "cleanup.txt"
        self.write_plugin(
            "rollback",
            "rollback.plugin",
            f"""
from pathlib import Path
def activate(context):
    context.register_cleanup(lambda: Path({str(marker)!r}).write_text("clean"))
    context.register_extension("agent", "rollback.plugin.agent", object())
""".strip()
            + "\n",
            capabilities=["prompt"],
        )
        manager = self.manager(["rollback.plugin"])
        with self.assertRaisesRegex(
            PluginRuntimeError,
            "capability_not_declared",
        ):
            await manager.activate_enabled()
        self.assertEqual(marker.read_text(encoding="utf-8"), "clean")
        self.assertEqual(manager.extensions("prompt"), {})

    async def test_later_activation_failure_rolls_back_prior_plugin(self) -> None:
        marker = self.root / "prior-deactivated.txt"
        self.write_plugin(
            "a-first",
            "first.plugin",
            f"""
from pathlib import Path
class Handle:
    def deactivate(self):
        Path({str(marker)!r}).write_text("deactivated")
def activate(context):
    context.register_extension("prompt", "first.plugin.prompt", "first")
    return Handle()
""".strip()
            + "\n",
        )
        self.write_plugin(
            "b-second",
            "second.plugin",
            "def activate(context):\n    raise RuntimeError('private detail')\n",
        )
        manager = self.manager(["first.plugin", "second.plugin"])
        with self.assertRaisesRegex(PluginRuntimeError, "activation_failed") as raised:
            await manager.activate_enabled()
        self.assertNotIn("private detail", str(raised.exception))
        self.assertEqual(marker.read_text(encoding="utf-8"), "deactivated")
        self.assertEqual(manager.extensions("prompt"), {})
        self.assertEqual(manager.catalog().active_plugins, [])

    async def test_deactivation_failure_is_reported_after_cleanup(self) -> None:
        marker = self.root / "cleanup-ran.txt"
        self.write_plugin(
            "deactivation",
            "deactivation.plugin",
            f"""
from pathlib import Path
class Handle:
    def deactivate(self):
        raise RuntimeError("private teardown detail")
def activate(context):
    context.register_extension(
        "prompt",
        "deactivation.plugin.prompt",
        "registered",
    )
    context.register_cleanup(
        lambda: Path({str(marker)!r}).write_text("cleaned")
    )
    return Handle()
""".strip()
            + "\n",
        )
        manager = self.manager(["deactivation.plugin"])
        await manager.activate_enabled()

        await manager.deactivate_all()

        self.assertEqual(marker.read_text(encoding="utf-8"), "cleaned")
        self.assertEqual(manager.extensions("prompt"), {})
        catalog = manager.catalog()
        self.assertEqual(catalog.active_plugins, [])
        self.assertEqual(catalog.plugins[0].state, "failed")
        self.assertEqual(catalog.plugins[0].error_code, "deactivation_failed")

    async def test_entry_point_must_be_local_single_file(self) -> None:
        self.write_plugin(
            "nested",
            "nested.plugin",
            "def activate(context):\n    return None\n",
            entry_point="nested.plugin:activate",
        )
        manager = self.manager(["nested.plugin"])
        with self.assertRaisesRegex(
            PluginRuntimeError,
            "runtime_entry_point_unsupported",
        ):
            await manager.activate_enabled()

    def test_permission_grant_configuration_is_strict(self) -> None:
        self.assertEqual(
            configured_permission_grants(
                '{"sample.plugin":["network","model_access"]}'
            ),
            {"sample.plugin": frozenset({"network", "model_access"})},
        )
        for value in (
            "[]",
            "not-json",
            '{"Bad ID":[]}',
            '{"sample.plugin":"network"}',
            '{"sample.plugin":["unknown"]}',
            '{"sample.plugin":["network","network"]}',
        ):
            with self.subTest(value=value):
                with self.assertRaises(PluginConfigurationError):
                    configured_permission_grants(value)


class PluginWorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_deactivates_plugins_when_worker_loop_fails(self) -> None:
        from app.workers import workflow_worker

        activate = AsyncMock()
        deactivate = AsyncMock()
        worker_loop = AsyncMock(side_effect=RuntimeError("worker failed"))
        with (
            patch.object(
                workflow_worker.plugin_runtime_manager,
                "activate_enabled",
                activate,
            ),
            patch.object(
                workflow_worker.plugin_runtime_manager,
                "deactivate_all",
                deactivate,
            ),
            patch.object(
                workflow_worker,
                "configured_permission_grants",
            ),
            patch.object(
                workflow_worker,
                "validate_plugin_configuration",
            ),
            patch.object(workflow_worker, "_run_worker_loop", worker_loop),
        ):
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                await workflow_worker.run_worker()
        activate.assert_awaited_once_with()
        deactivate.assert_awaited_once_with()


class PluginBackendLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_cancellation_deactivates_plugins(self) -> None:
        from app import main

        catalog = SimpleNamespace(
            plugins=[],
            configured_enabled=["sample.plugin"],
            execution_enabled=True,
            active_plugins=["sample.plugin"],
        )
        activate = AsyncMock(return_value=catalog)
        deactivate = AsyncMock()
        with (
            patch.object(
                main.schema_migration_service,
                "assert_runtime_compatible",
                return_value=SimpleNamespace(authorities=[]),
            ),
            patch.object(main, "validate_auth_configuration"),
            patch.object(main, "configured_permission_grants"),
            patch.object(main, "validate_plugin_configuration"),
            patch.object(
                main.plugin_runtime_manager,
                "activate_enabled",
                activate,
            ),
            patch.object(
                main.plugin_runtime_manager,
                "deactivate_all",
                deactivate,
            ),
            patch.object(
                main.memory_index_consistency_service,
                "check_and_repair",
                AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                async with main.lifespan(main.app):
                    self.fail("Cancelled startup must not yield")
        activate.assert_awaited_once_with()
        deactivate.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
