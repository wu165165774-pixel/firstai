import asyncio
import unittest

from fastapi.testclient import TestClient

from app.config.settings import settings
from app.llm.base import BaseChatProvider
from app.llm.exceptions import ProviderConfigurationError
from app.llm.manager import LLMManager
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai_cloud import OpenAIProvider
from app.llm.providers.claude import ClaudeProvider
from app.llm.providers.dashscope import DashScopeProvider
from app.llm.providers.qwen_local import QwenLocalProvider
from app.llm.registry import ProviderRegistry
from app.llm.schemas import (
    ChatRequest,
    ChatResponse,
    ProviderDescriptor,
)
from app.main import app


class HealthyProvider(BaseChatProvider):
    name = "healthy"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="ok", model="fake", provider=self.name)

    async def stream_chat(self, request: ChatRequest):
        yield "ok"

    async def health(self) -> bool:
        await asyncio.sleep(0.01)
        return True


class SlowProvider(HealthyProvider):
    name = "slow"

    async def health(self) -> bool:
        await asyncio.sleep(0.2)
        return True


class ProviderCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_does_not_instantiate_without_probe(self) -> None:
        calls = 0

        def factory() -> HealthyProvider:
            nonlocal calls
            calls += 1
            return HealthyProvider()

        registry = ProviderRegistry()
        registry.register(
            "healthy",
            factory,
            descriptor=ProviderDescriptor(
                name="healthy",
                kind="local",
                default_model="fake",
                supported_models=["fake"],
                reasoning_efforts=["none"],
            ),
            configuration_check=lambda: True,
        )
        status = (await LLMManager(registry).provider_status())[0]
        self.assertEqual(calls, 0)
        self.assertTrue(status.configured)
        self.assertIsNone(status.available)
        self.assertEqual(status.default_model, "fake")

    async def test_health_probes_are_bounded_and_sanitized(self) -> None:
        registry = ProviderRegistry()
        registry.register(
            "healthy",
            HealthyProvider,
            descriptor=ProviderDescriptor(name="healthy", kind="local"),
        )
        registry.register(
            "slow",
            SlowProvider,
            descriptor=ProviderDescriptor(name="slow", kind="cloud"),
        )
        statuses = await LLMManager(registry).provider_status(
            probe=True,
            timeout_ms=50,
        )
        by_name = {item.name: item for item in statuses}
        self.assertTrue(by_name["healthy"].available)
        self.assertIsNone(by_name["healthy"].health_error)
        self.assertFalse(by_name["slow"].available)
        self.assertEqual(by_name["slow"].health_error, "health_check_timed_out")

    async def test_unconfigured_provider_is_not_instantiated(self) -> None:
        registry = ProviderRegistry()

        def forbidden_factory() -> HealthyProvider:
            raise AssertionError("unconfigured provider must not be instantiated")

        registry.register(
            "cloud",
            forbidden_factory,
            descriptor=ProviderDescriptor(
                name="cloud",
                kind="cloud",
                requires_api_key=True,
            ),
            configuration_check=lambda: False,
        )
        status = (
            await LLMManager(registry).provider_status(probe=True)
        )[0]
        self.assertFalse(status.configured)
        self.assertFalse(status.available)
        self.assertEqual(status.health_error, "not_configured")


class ProviderConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_qwen_url = settings.qwen_base_url
        self.old_qwen_model = settings.qwen_model
        self.old_deepseek_key = settings.deepseek_api_key
        self.old_deepseek_url = settings.deepseek_base_url
        self.old_deepseek_model = settings.deepseek_model
        self.old_openai_key = settings.openai_api_key
        self.old_openai_url = settings.openai_base_url
        self.old_openai_model = settings.openai_model
        self.old_claude_key = settings.claude_api_key
        self.old_claude_url = settings.claude_base_url
        self.old_claude_model = settings.claude_model
        self.old_claude_max_tokens = settings.claude_max_tokens
        self.old_dashscope_key = settings.dashscope_api_key
        self.old_dashscope_url = settings.dashscope_base_url
        self.old_dashscope_model = settings.dashscope_model

    def tearDown(self) -> None:
        settings.qwen_base_url = self.old_qwen_url
        settings.qwen_model = self.old_qwen_model
        settings.deepseek_api_key = self.old_deepseek_key
        settings.deepseek_base_url = self.old_deepseek_url
        settings.deepseek_model = self.old_deepseek_model
        settings.openai_api_key = self.old_openai_key
        settings.openai_base_url = self.old_openai_url
        settings.openai_model = self.old_openai_model
        settings.claude_api_key = self.old_claude_key
        settings.claude_base_url = self.old_claude_url
        settings.claude_model = self.old_claude_model
        settings.claude_max_tokens = self.old_claude_max_tokens
        settings.dashscope_api_key = self.old_dashscope_key
        settings.dashscope_base_url = self.old_dashscope_url
        settings.dashscope_model = self.old_dashscope_model

    def test_qwen_uses_settings_and_normalizes_openai_path(self) -> None:
        settings.qwen_base_url = "http://example.test:11434"
        settings.qwen_model = "qwen-test"
        provider = QwenLocalProvider()
        self.assertEqual(str(provider.client.base_url), "http://example.test:11434/v1/")
        self.assertEqual(provider.model, "qwen-test")

    def test_deepseek_requires_configuration(self) -> None:
        settings.deepseek_api_key = ""
        with self.assertRaisesRegex(
            ProviderConfigurationError,
            "not configured",
        ):
            DeepSeekProvider()

    def test_deepseek_uses_configured_endpoint_and_model(self) -> None:
        settings.deepseek_api_key = "test-provider-key"
        settings.deepseek_base_url = "https://deepseek.example.test"
        settings.deepseek_model = "deepseek-test"
        provider = DeepSeekProvider()
        self.assertEqual(
            str(provider.client.base_url),
            "https://deepseek.example.test",
        )
        self.assertEqual(provider.model, "deepseek-test")

    def test_new_cloud_providers_require_keys(self) -> None:
        cases = (
            ("openai_api_key", OpenAIProvider),
            ("claude_api_key", ClaudeProvider),
            ("dashscope_api_key", DashScopeProvider),
        )
        for field, provider_type in cases:
            with self.subTest(provider=provider_type.name):
                setattr(settings, field, "")
                with self.assertRaisesRegex(
                    ProviderConfigurationError,
                    "not configured",
                ):
                    provider_type()

    def test_new_cloud_providers_use_configured_endpoints(self) -> None:
        settings.openai_api_key = "test-openai-key"
        settings.openai_base_url = "https://openai.example.test/v1"
        settings.openai_model = "openai-test"
        openai = OpenAIProvider()
        self.assertEqual(
            str(openai.client.base_url),
            "https://openai.example.test/v1/",
        )
        self.assertEqual(openai.model, "openai-test")

        settings.claude_api_key = "test-claude-key"
        settings.claude_base_url = "https://claude.example.test"
        settings.claude_model = "claude-test"
        claude = ClaudeProvider()
        self.assertEqual(
            str(claude.client.base_url),
            "https://claude.example.test",
        )
        self.assertEqual(claude.model, "claude-test")

        settings.dashscope_api_key = "test-dashscope-key"
        settings.dashscope_base_url = "https://dashscope.example.test/v1"
        settings.dashscope_model = "dashscope-test"
        dashscope = DashScopeProvider()
        self.assertEqual(
            str(dashscope.client.base_url),
            "https://dashscope.example.test/v1/",
        )
        self.assertEqual(dashscope.model, "dashscope-test")


class ProviderCatalogApiTests(unittest.TestCase):
    def test_catalog_is_backward_compatible_and_secret_free(self) -> None:
        response = TestClient(app).get("/api/v1/providers")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(
            data["providers"],
            ["claude", "dashscope", "deepseek", "openai", "qwen_local"],
        )
        self.assertFalse(data["probed"])
        by_name = {item["name"]: item for item in data["catalog"]}
        self.assertEqual(
            by_name["deepseek"]["configured"],
            bool(settings.deepseek_api_key.strip()),
        )
        self.assertTrue(by_name["qwen_local"]["configured"])
        self.assertEqual(
            by_name["openai"]["configured"],
            all(
                (
                    settings.openai_api_key.strip(),
                    settings.openai_base_url.strip(),
                    settings.openai_model.strip(),
                )
            ),
        )
        self.assertEqual(
            by_name["claude"]["configured"],
            all(
                (
                    settings.claude_api_key.strip(),
                    settings.claude_base_url.strip(),
                    settings.claude_model.strip(),
                )
            ),
        )
        self.assertEqual(
            by_name["dashscope"]["configured"],
            all(
                (
                    settings.dashscope_api_key.strip(),
                    settings.dashscope_base_url.strip(),
                    settings.dashscope_model.strip(),
                )
            ),
        )
        expected_fields = {
            "name",
            "kind",
            "registered",
            "configured",
            "available",
            "default_model",
            "supported_models",
            "streaming",
            "reasoning_efforts",
            "requires_api_key",
            "latency_ms",
            "health_error",
        }
        self.assertEqual(set(by_name["deepseek"]), expected_fields)
        serialized = str(data)
        for secret in (
            settings.openai_api_key,
            settings.claude_api_key,
            settings.dashscope_api_key,
        ):
            if secret:
                self.assertNotIn(secret, serialized)
        self.assertIn(
            by_name["deepseek"]["health_error"],
            {None, "not_configured", "health_check_failed", "health_check_timed_out"},
        )

        operation = app.openapi()["paths"]["/api/v1/providers"]["get"]
        parameter_names = {item["name"] for item in operation["parameters"]}
        self.assertEqual(parameter_names, {"probe", "timeout_ms"})


if __name__ == "__main__":
    unittest.main()
