from app.llm.manager import LLMManager
from app.llm.providers.claude import ClaudeProvider
from app.llm.providers.dashscope import DashScopeProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai_cloud import OpenAIProvider
from app.llm.providers.qwen_local import QwenLocalProvider
from app.llm.registry import ProviderRegistry
from app.llm.schemas import ProviderDescriptor
from app.config.settings import get_settings


settings = get_settings()
provider_registry = ProviderRegistry()

provider_registry.register(
    "claude",
    ClaudeProvider,
    descriptor=ProviderDescriptor(
        name="claude",
        kind="cloud",
        default_model=settings.claude_model,
        supported_models=list(
            dict.fromkeys(
                [
                    settings.claude_model,
                    "claude-sonnet-5",
                    "claude-opus-5",
                    "claude-haiku-4-5-20251001",
                ]
            )
        ),
        streaming=True,
        reasoning_efforts=["none"],
        requires_api_key=True,
    ),
    configuration_check=lambda: all(
        (
            settings.claude_api_key.strip(),
            settings.claude_base_url.strip(),
            settings.claude_model.strip(),
        )
    ),
)

provider_registry.register(
    "dashscope",
    DashScopeProvider,
    descriptor=ProviderDescriptor(
        name="dashscope",
        kind="cloud",
        default_model=settings.dashscope_model,
        supported_models=list(
            dict.fromkeys(
                [
                    settings.dashscope_model,
                    "qwen3.7-plus",
                    "qwen3.7-max",
                    "qwen-flash",
                ]
            )
        ),
        streaming=True,
        reasoning_efforts=["none", "medium"],
        requires_api_key=True,
    ),
    configuration_check=lambda: all(
        (
            settings.dashscope_api_key.strip(),
            settings.dashscope_base_url.strip(),
            settings.dashscope_model.strip(),
        )
    ),
)

provider_registry.register(
    "deepseek",
    DeepSeekProvider,
    descriptor=ProviderDescriptor(
        name="deepseek",
        kind="cloud",
        default_model=settings.deepseek_model,
        supported_models=list(
            dict.fromkeys(
                [settings.deepseek_model, "deepseek-chat", "deepseek-reasoner"]
            )
        ),
        streaming=True,
        reasoning_efforts=["none"],
        requires_api_key=True,
    ),
    configuration_check=lambda: bool(
        settings.deepseek_api_key.strip()
    ),
)

provider_registry.register(
    "openai",
    OpenAIProvider,
    descriptor=ProviderDescriptor(
        name="openai",
        kind="cloud",
        default_model=settings.openai_model,
        supported_models=list(
            dict.fromkeys(
                [
                    settings.openai_model,
                    "gpt-5.6-luna",
                    "gpt-5.6-terra",
                    "gpt-5.6-sol",
                ]
            )
        ),
        streaming=True,
        reasoning_efforts=["none", "low", "medium", "high"],
        requires_api_key=True,
    ),
    configuration_check=lambda: all(
        (
            settings.openai_api_key.strip(),
            settings.openai_base_url.strip(),
            settings.openai_model.strip(),
        )
    ),
)

provider_registry.register(
    "qwen_local",
    QwenLocalProvider,
    descriptor=ProviderDescriptor(
        name="qwen_local",
        kind="local",
        default_model=settings.qwen_model,
        supported_models=[settings.qwen_model],
        streaming=True,
        reasoning_efforts=["none", "low", "medium", "high"],
        requires_api_key=False,
    ),
    configuration_check=lambda: bool(
        settings.qwen_base_url.strip()
        and settings.qwen_model.strip()
    ),
)

# 保留旧名称，兼容现有 chat.py 和 providers.py。
registry = provider_registry

# 全局统一 LLM 调度入口。
llm_manager = LLMManager(
    provider_registry
)
