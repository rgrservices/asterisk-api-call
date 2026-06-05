from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    host: str = "127.0.0.1"
    port: int = 8000

    call_api_tokens_file: Path
    call_api_companies_file: Path

    access_log_path: Path = Field(default=Path("logs/access.log"))


def get_settings() -> Settings:
    return Settings()
