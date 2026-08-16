from typing import Any

from app.config.settings import get_settings
from app.llm.exceptions import ProviderConfigurationError
from app.llm.providers.openai_compatible import OpenAICompatibleProvider


class DashScopeProvider(OpenAICompatibleProvider):
    name = "dashscope"

    def __init__(self, *, client: Any | None = None) -> None:
        settings = get_settings()
        if not all(
            (
                settings.dashscope_api_key.strip(),
                settings.dashscope_base_url.strip(),
                settings.dashscope_model.strip(),
            )
        ):
            raise ProviderConfigurationError(
                "DashScope provider is not configured."
            )
        super().__init__(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            model=settings.dashscope_model,
            max_tokens_parameter="max_tokens",
            reasoning_mode="dashscope",
            client=client,
        )
