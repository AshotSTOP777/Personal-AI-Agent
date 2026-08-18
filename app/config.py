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

    # Speech-to-text (голосовые сообщения). Пусто/неизвестное значение = функция выключена.
    stt_provider: str = Field(default="openrouter")  # "" | "groq" | "openrouter"
    groq_api_key: str = Field(default="")
    stt_model: str = Field(default="openai/whisper-large-v3:free")
    voice_max_duration_seconds: int = Field(default=300)

    # Gmail API (OAuth2, HTTPS) — используется по умолчанию, если настроен.
    gmail_client_id: str = Field(default="")
    gmail_client_secret: str = Field(default="")
    gmail_refresh_token: str = Field(default="")
    gmail_address: str = Field(default="")

    # Email через SMTP + IMAP — fallback, если Gmail API не настроен. Пусто = функция выключена.
    email_address: str = Field(default="")
    email_password: str = Field(default="")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=465)
    imap_host: str = Field(default="")
    imap_port: int = Field(default=993)

    # Browser automation (Playwright)
    browser_timeout_ms: int = Field(default=15000)
    browser_headless: bool = Field(default=True)
    browser_profile_dir: str = Field(default=".browser-profile")

    # Database
    database_url: str = Field(default="postgresql+asyncpg://user:password@localhost:5432/personal_ai_agent")

    # Cost / token control
    daily_token_limit: int = Field(default=200_000)
    conversation_history_window: int = Field(default=10)

    # Reminder worker
    reminder_poll_interval_seconds: int = Field(default=30)

    # Долгоживущие фоновые задания (Job)
    job_poll_interval_seconds: int = Field(default=60)
    job_max_runs: int = Field(default=100)

    # Часовой пояс владельца (IANA name), используется для интерпретации "завтра в 15:00" и т.п.
    user_timezone: str = Field(default="Europe/Moscow")

    # Logging
    log_level: str = Field(default="INFO")


settings = Settings()
