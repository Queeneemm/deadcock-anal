from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    deadlock_api_base_url: str = Field(default="https://api.deadlock-api.com/v1/", alias="DEADLOCK_API_BASE_URL")
    deadlock_assets_base_url: str = Field(default="https://assets.deadlock-api.com/v2/", alias="DEADLOCK_ASSETS_BASE_URL")
    database_url: str = Field(default="sqlite:///data/bot.db", alias="DATABASE_URL")
    poll_interval_seconds: int = Field(default=60, alias="POLL_INTERVAL_SECONDS")
    request_timeout_seconds: int = Field(default=20, alias="REQUEST_TIMEOUT_SECONDS")
    asset_cache_dir: Path = Field(default=Path("cache/assets"), alias="ASSET_CACHE_DIR")
    card_output_dir: Path = Field(default=Path("cards"), alias="CARD_OUTPUT_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def get_settings() -> Settings:
    return Settings()
