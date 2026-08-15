from app.llm.manager import LLMManager
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.qwen_local import QwenLocalProvider
from app.llm.registry import ProviderRegistry
from app.llm.schemas import ProviderDescriptor
from app.config.settings import get_settings


settings = get_settings()
provider_registry = ProviderRegistry()

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
