from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация приложения. Значения читаются из переменных окружения / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: str = Field(default="")
    telegram_owner_id: int = Field(default=0)

    # AI provider selection
    ai_provider: str = Field(default="anthropic")  # "anthropic" | "gemini" | "openrouter"

    # Anthropic
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-5")

    # Gemini
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # OpenRouter (OpenAI-compatible API)
    openrouter_api_key: str = Field(default="")
    openrouter_model: str = Field(default="openrouter/free")

    # Database
    database_url: str = Field(default="postgresql+asyncpg://user:password@localhost:5432/personal_ai_agent")

    # Cost / token control
    daily_token_limit: int = Field(default=200_000)
    conversation_history_window: int = Field(default=10)

    # Reminder worker
    reminder_poll_interval_seconds: int = Field(default=30)

    # Logging
    log_level: str = Field(default="INFO")


settings = Settings()
