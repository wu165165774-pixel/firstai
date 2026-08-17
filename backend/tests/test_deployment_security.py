import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.deployment_security import (
    DeploymentSecurityError,
    validate_deployment_security,
)


class DeploymentSecurityTests(unittest.TestCase):
    def test_loopback_allows_local_development_without_authentication(self) -> None:
        status = validate_deployment_security(
            bind_host="127.0.0.1",
            auth_enabled=False,
            debug_enabled=True,
            allow_insecure_network_exposure=False,
        )
        self.assertTrue(status.loopback_only)
        self.assertFalse(status.auth_enabled)
        self.assertTrue(status.debug_enabled)

    def test_non_loopback_requires_authentication_and_debug_off(self) -> None:
        for auth_enabled, debug_enabled in (
            (False, False),
            (False, True),
            (True, True),
        ):
            with self.subTest(
                auth_enabled=auth_enabled,
                debug_enabled=debug_enabled,
            ):
                with self.assertRaises(DeploymentSecurityError) as raised:
                    validate_deployment_security(
                        bind_host="0.0.0.0",
                        auth_enabled=auth_enabled,
                        debug_enabled=debug_enabled,
                        allow_insecure_network_exposure=False,
                    )
                self.assertEqual(raised.exception.code, "unsafe_network_exposure")

    def test_authenticated_non_loopback_production_exposure_is_allowed(self) -> None:
        status = validate_deployment_security(
            bind_host="192.168.10.20",
            auth_enabled=True,
            debug_enabled=False,
            allow_insecure_network_exposure=False,
        )
        self.assertFalse(status.loopback_only)
        self.assertTrue(status.auth_enabled)
        self.assertFalse(status.debug_enabled)
        self.assertFalse(status.insecure_override)

    def test_explicit_insecure_override_is_visible(self) -> None:
        status = validate_deployment_security(
            bind_host="0.0.0.0",
            auth_enabled=False,
            debug_enabled=True,
            allow_insecure_network_exposure=True,
        )
        self.assertFalse(status.loopback_only)
        self.assertTrue(status.insecure_override)

    def test_bind_host_must_be_a_literal_ipv4_address(self) -> None:
        for bind_host in ("", "localhost", "::1", "not-an-address"):
            with self.subTest(bind_host=bind_host):
                with self.assertRaises(DeploymentSecurityError) as raised:
                    validate_deployment_security(
                        bind_host=bind_host,
                        auth_enabled=True,
                        debug_enabled=False,
                    )
                self.assertEqual(raised.exception.code, "invalid_bind_host")


class DeploymentSecurityLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsafe_exposure_blocks_before_plugin_activation(self) -> None:
        from app import main

        activate = AsyncMock()
        with (
            patch.object(
                main.schema_migration_service,
                "assert_runtime_compatible",
                return_value=SimpleNamespace(authorities=[]),
            ),
            patch.object(main, "validate_auth_configuration"),
            patch.object(
                main,
                "validate_deployment_security",
                side_effect=DeploymentSecurityError("unsafe_network_exposure"),
            ),
            patch.object(
                main.plugin_runtime_manager,
                "activate_enabled",
                activate,
            ),
        ):
            with self.assertRaises(DeploymentSecurityError) as raised:
                async with main.lifespan(main.app):
                    self.fail("Unsafe deployment must not yield")
        self.assertEqual(raised.exception.code, "unsafe_network_exposure")
        activate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
