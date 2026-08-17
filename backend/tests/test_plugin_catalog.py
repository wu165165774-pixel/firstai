import json
import tempfile
import unittest

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.v1 import plugins as plugins_api
from app.config.settings import settings
from app.main import app
from app.plugins.service import (
    PluginCatalogService,
    PluginConfigurationError,
    configured_plugin_ids,
    validate_plugin_configuration,
)
from app.plugins.runtime import PluginRuntimeManager
from app.plugins.versioning import parse_semantic_version
from app.version import APP_VERSION


def manifest(
    plugin_id: str,
    *,
    plugin_api: int = 1,
    minimum: str = APP_VERSION,
    maximum: str | None = "2.0.0",
) -> dict:
    requires = {
        "plugin_api": plugin_api,
        "min_core_version": minimum,
    }
    if maximum is not None:
        requires["max_core_version_exclusive"] = maximum
    return {
        "manifest_version": 1,
        "plugin_id": plugin_id,
        "name": f"Plugin {plugin_id}",
        "version": "1.2.3-alpha.1",
        "description": "Catalog-only fixture",
        "entry_point": "fixture.plugin:activate",
        "capabilities": ["prompt", "llm_provider"],
        "permissions": ["model_access", "network"],
        "requires": requires,
    }


class PluginCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_plugin(self, package: str, payload: dict | str) -> Path:
        directory = self.root / package
        directory.mkdir()
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (directory / "novelforge-plugin.json").write_text(
            text,
            encoding="utf-8",
        )
        return directory

    def service(self, enabled: list[str] | None = None) -> PluginCatalogService:
        return PluginCatalogService(
            plugin_root=self.root,
            enabled_json=json.dumps(enabled or []),
        )

    def test_semantic_version_precedence_and_validation(self) -> None:
        self.assertLess(
            parse_semantic_version("0.15.0-alpha.9"),
            parse_semantic_version("0.15.0-alpha.10"),
        )
        self.assertLess(
            parse_semantic_version("0.15.0-alpha.38"),
            parse_semantic_version("0.15.0"),
        )
        self.assertLess(
            parse_semantic_version("0.15.0"),
            parse_semantic_version("1.0.0"),
        )
        with self.assertRaises(ValueError):
            parse_semantic_version("1.0.0-alpha.01")

    def test_valid_plugin_is_disabled_by_default_and_secret_free(self) -> None:
        self.add_plugin("sample", manifest("sample.plugin"))
        catalog = self.service().catalog()
        self.assertTrue(catalog.configuration_valid)
        self.assertFalse(catalog.execution_enabled)
        self.assertEqual(catalog.configured_enabled, [])
        item = catalog.plugins[0]
        self.assertEqual(item.state, "disabled")
        self.assertTrue(item.compatible)
        self.assertFalse(item.activation_allowed)
        self.assertFalse(item.loaded)
        self.assertEqual(item.permissions, ["model_access", "network"])
        serialized = json.dumps(catalog.model_dump())
        self.assertNotIn(str(self.root), serialized)

    def test_exact_allow_list_marks_compatible_plugin_activation_ready(self) -> None:
        self.add_plugin("sample", manifest("sample.plugin"))
        catalog = self.service(["sample.plugin"]).catalog()
        self.assertTrue(catalog.configuration_valid)
        item = catalog.plugins[0]
        self.assertEqual(item.state, "enabled")
        self.assertTrue(item.enabled)
        self.assertTrue(item.activation_allowed)
        self.assertFalse(item.loaded)

    def test_incompatible_plugins_are_never_activation_ready(self) -> None:
        cases = (
            ("wrong-api", manifest("wrong.api", plugin_api=2), "plugin_api_incompatible"),
            (
                "too-new",
                manifest("too.new", minimum="1.0.1", maximum="2.0.0"),
                "core_version_too_old",
            ),
            (
                "too-old",
                manifest("too.old", minimum="0.1.0", maximum="0.15.0-alpha.38"),
                "core_version_too_new",
            ),
        )
        for package, payload, _ in cases:
            self.add_plugin(package, payload)
        enabled = [payload["plugin_id"] for _, payload, _ in cases]
        catalog = self.service(enabled).catalog()
        by_id = {item.plugin_id: item for item in catalog.plugins}
        for _, payload, error_code in cases:
            item = by_id[payload["plugin_id"]]
            self.assertEqual(item.state, "incompatible")
            self.assertEqual(item.error_code, error_code)
            self.assertFalse(item.activation_allowed)
        self.assertFalse(catalog.configuration_valid)

    def test_discovery_never_imports_or_executes_entry_point(self) -> None:
        directory = self.add_plugin("danger", manifest("danger.plugin"))
        marker = directory / "executed.txt"
        (directory / "fixture.py").write_text(
            "from pathlib import Path\nPath(__file__).with_name('executed.txt').write_text('bad')\n",
            encoding="utf-8",
        )
        catalog = self.service(["danger.plugin"]).catalog()
        self.assertTrue(catalog.plugins[0].activation_allowed)
        self.assertFalse(catalog.plugins[0].loaded)
        self.assertFalse(marker.exists())

    def test_invalid_duplicate_and_missing_enabled_plugins_fail_closed(self) -> None:
        self.add_plugin("invalid", "{not-json")
        self.add_plugin("duplicate-a", manifest("duplicate.plugin"))
        self.add_plugin("duplicate-b", manifest("duplicate.plugin"))
        catalog = self.service(["duplicate.plugin", "missing.plugin"]).catalog()
        duplicate_items = [
            item for item in catalog.plugins if item.plugin_id == "duplicate.plugin"
        ]
        self.assertEqual(len(duplicate_items), 2)
        self.assertTrue(
            all(item.error_code == "duplicate_plugin_id" for item in duplicate_items)
        )
        self.assertEqual(catalog.unknown_enabled, ["missing.plugin"])
        self.assertFalse(catalog.configuration_valid)
        with self.assertRaises(PluginConfigurationError):
            validate_plugin_configuration(
                self.service(["duplicate.plugin", "missing.plugin"])
            )

    def test_missing_and_oversized_manifests_are_bounded_without_loading(self) -> None:
        (self.root / "missing").mkdir()
        oversized = self.root / "oversized"
        oversized.mkdir()
        (oversized / "novelforge-plugin.json").write_bytes(b"x" * (64 * 1024 + 1))
        catalog = self.service().catalog()
        by_package = {item.package: item for item in catalog.plugins}
        self.assertEqual(by_package["missing"].error_code, "manifest_missing")
        self.assertEqual(
            by_package["oversized"].error_code,
            "manifest_too_large",
        )
        self.assertTrue(catalog.configuration_valid)

    def test_configuration_json_and_absent_root_are_deterministic(self) -> None:
        self.assertEqual(configured_plugin_ids('["b.plugin", "a.plugin"]'), (
            "a.plugin",
            "b.plugin",
        ))
        for value in ("{}", "not-json", '["same", "same"]', '["Bad ID"]'):
            with self.subTest(value=value):
                with self.assertRaises(PluginConfigurationError):
                    configured_plugin_ids(value)
        missing = PluginCatalogService(
            plugin_root=self.root / "missing",
            enabled_json="[]",
        ).catalog()
        self.assertFalse(missing.root_available)
        self.assertTrue(missing.configuration_valid)
        self.assertEqual(missing.plugins, [])


class PluginCatalogApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_runtime = plugins_api.plugin_runtime_manager
        self.previous_auth_enabled = settings.auth_enabled
        self.previous_tokens = settings.auth_tokens_json
        plugins_api.plugin_runtime_manager = PluginRuntimeManager(
            PluginCatalogService(
                plugin_root=self.temp_dir.name,
                enabled_json="[]",
                execution_enabled=False,
            )
        )
        settings.auth_enabled = True
        settings.auth_tokens_json = json.dumps(
            {
                "plugin-user-token-123456": {
                    "user_id": "plugin-user",
                    "roles": ["user"],
                },
                "plugin-admin-token-12345": {
                    "user_id": "plugin-admin",
                    "roles": ["admin"],
                },
            }
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        plugins_api.plugin_runtime_manager = self.previous_runtime
        settings.auth_enabled = self.previous_auth_enabled
        settings.auth_tokens_json = self.previous_tokens
        self.temp_dir.cleanup()

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_catalog_is_admin_only_and_registered_in_openapi(self) -> None:
        self.assertEqual(self.client.get("/api/v1/plugins").status_code, 401)
        user = self.client.get(
            "/api/v1/plugins",
            headers=self.headers("plugin-user-token-123456"),
        )
        self.assertEqual(user.status_code, 403)
        admin = self.client.get(
            "/api/v1/plugins",
            headers=self.headers("plugin-admin-token-12345"),
        )
        self.assertEqual(admin.status_code, 200)
        data = admin.json()["data"]
        self.assertEqual(data["plugin_api_version"], 1)
        self.assertFalse(data["execution_enabled"])
        self.assertTrue(data["configuration_valid"])

        operation = app.openapi()["paths"]["/api/v1/plugins"]["get"]
        self.assertEqual(operation["security"], [{"BearerAuth": []}])
        self.assertEqual(operation["tags"], ["Plugins"])


if __name__ == "__main__":
    unittest.main()
