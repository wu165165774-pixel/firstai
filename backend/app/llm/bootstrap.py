from app.llm.registry import ProviderRegistry

from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.qwen_local import QwenLocalProvider


registry = ProviderRegistry()


registry.register(
    "deepseek",
    DeepSeekProvider,
)


registry.register(
    "qwen_local",
    QwenLocalProvider,
)
print(registry.list())