from app.llm.manager import LLMManager
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.qwen_local import QwenLocalProvider
from app.llm.registry import ProviderRegistry


provider_registry = ProviderRegistry()

provider_registry.register(
    "deepseek",
    DeepSeekProvider,
)

provider_registry.register(
    "qwen_local",
    QwenLocalProvider,
)

# 保留旧名称，兼容现有 chat.py 和 providers.py。
registry = provider_registry

# 全局统一 LLM 调度入口。
llm_manager = LLMManager(
    provider_registry
)
