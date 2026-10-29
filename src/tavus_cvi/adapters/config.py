"""Validated process configuration. Reads secrets from one place."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from `.local_secrets/.env`."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".local_secrets" / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tavus_api_key: str = Field(default="", alias="TAVUS_API_KEY")
    database_url: str = Field(
        default="postgresql://localhost/tavus_interviewer",
        alias="DATABASE_URL",
    )
    callback_base_url: str = ""
    callback_secret: str = ""
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    call_limit_seconds: int = 3600
    tavus_base_url: str = "https://tavusapi.com"
    recordings_dir: Path = REPO_ROOT / "recordings"
    agent_config_dir: Path = REPO_ROOT / "config" / "agents"


def load_settings() -> Settings:
    """Return the process settings."""
    return Settings()
