from typing import Any

from app.config.settings import get_settings
from app.llm.exceptions import ProviderConfigurationError
from app.llm.providers.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(self, *, client: Any | None = None) -> None:
        settings = get_settings()
        if not all(
            (
                settings.openai_api_key.strip(),
                settings.openai_base_url.strip(),
                settings.openai_model.strip(),
            )
        ):
            raise ProviderConfigurationError(
                "OpenAI provider is not configured."
            )
        super().__init__(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            max_tokens_parameter="max_completion_tokens",
            reasoning_mode="openai",
            client=client,
        )
