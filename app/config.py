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

    # Legacy YAML paths — usados somente pelo script de migração
    call_api_tokens_file: Path = Field(default=Path("examples/tokens.example.yaml"))
    call_api_companies_file: Path = Field(default=Path("examples/companies.example.yaml"))

    # Banco de dados SQLite
    db_path: Path = Field(default=Path("call_api.db"))

    # Log de acesso
    access_log_path: Path = Field(default=Path("logs/access.log"))

    # AMI — Asterisk Manager Interface
    ami_host: str = "127.0.0.1"
    ami_port: int = 5038
    ami_user: str = ""
    ami_secret: str = ""
    ami_originate_timeout_ms: int = 30000
    ami_context: str = "call-api-playback"

    # Áudio — gravações
    sounds_base_dir: Path = Field(default=Path("/var/lib/asterisk/sounds"))
    recordings_base_path: str = "custom"

    # Admin UI
    admin_user: str = "admin"
    admin_password: str = ""
    admin_secret_key: str = "change-me-in-production"


def get_settings() -> Settings:
    return Settings()
