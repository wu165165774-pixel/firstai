from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    app_name: str = "NovelForge"

    api_version: str = "v1"

    debug: bool = True


    # DeepSeek

    deepseek_api_key: str = ""

    deepseek_base_url: str = (
        "https://api.deepseek.com"
    )


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()