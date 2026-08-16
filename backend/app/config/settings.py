from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    app_name: str = "NovelForge"

    api_version: str = "v1"

    debug: bool = True

    # Authentication is opt-in for local development. When enabled,
    # tokens are loaded from a JSON object without ever being returned
    # by an API. Example value:
    # {"long-secret":{"user_id":"alice","roles":["user"]}}
    auth_enabled: bool = False

    auth_tokens_json: str = "{}"


    # DeepSeek

    deepseek_api_key: str = ""

    deepseek_base_url: str = (
        "https://api.deepseek.com"
    )

    deepseek_model: str = "deepseek-chat"

    # OpenAI cloud API.
    openai_api_key: str = ""

    openai_base_url: str = "https://api.openai.com/v1"

    openai_model: str = "gpt-5.6-luna"

    # Anthropic Claude Messages API.
    claude_api_key: str = ""

    claude_base_url: str = "https://api.anthropic.com"

    claude_model: str = "claude-sonnet-5"

    claude_max_tokens: int = Field(default=4096, gt=0, le=128_000)

    # Alibaba Cloud Model Studio OpenAI-compatible API (Beijing).
    dashscope_api_key: str = ""

    dashscope_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    dashscope_model: str = "qwen-plus"

    # Local Qwen / Ollama OpenAI-compatible endpoint.
    qwen_base_url: str = "http://ollama:11434"

    qwen_model: str = "qwen3:8b"


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
