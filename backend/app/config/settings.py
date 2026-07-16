from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    app_name: str = "NovelForge"

    debug: bool = True

    api_version: str = "v1"


    class Config:
        env_file = ".env"



settings = Settings()