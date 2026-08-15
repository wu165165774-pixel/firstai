from functools import lru_cache

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
