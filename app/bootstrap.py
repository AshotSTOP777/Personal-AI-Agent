from __future__ import annotations

import asyncio

from app.config import settings
from app.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)


async def check_telegram() -> str:
    if not settings.telegram_bot_token:
        return "FAIL (TELEGRAM_BOT_TOKEN не задан)"
    from aiogram import Bot

    bot = Bot(token=settings.telegram_bot_token)
    try:
        me = await bot.get_me()
        return f"OK (@{me.username})"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"
    finally:
        await bot.session.close()


async def check_llm() -> str:
    try:
        from app.ai.factory import build_provider

        provider = build_provider(settings)
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"
    try:
        response = await provider.generate(
            "Отвечай одним словом.",
            [{"role": "user", "content": [{"type": "text", "text": "Скажи 'ок'."}]}],
            [],
        )
        return "OK" if response.text.strip() else "FAIL (пустой ответ)"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"


async def check_database() -> str:
    try:
        from sqlalchemy import text

        from app.db.session import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"


def check_migrations() -> str:
    try:
        from alembic import command
        from alembic.config import Config

        config = Config("alembic.ini")
        command.upgrade(config, "head")
        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"


def check_playwright_chromium() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "FAIL (pip install playwright)"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return "OK"
    except Exception:  # noqa: BLE001
        try:
            import subprocess
            import sys

            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, timeout=300)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return "OK (Chromium установлен автоматически)"
        except Exception as exc:  # noqa: BLE001
            return f"FAIL ({exc})"


async def check_avito() -> str:
    try:
        from app.avito.scraper import is_logged_in
        from app.browser.session import browser_session

        page = await browser_session.get_page()
        await page.goto("https://www.avito.ru", timeout=browser_session.timeout_ms)
        logged_in = await is_logged_in(page, timeout_ms=browser_session.timeout_ms)
        return "OK (авторизован)" if logged_in else "OK (публичный доступ; для отправки нужен /avito_login)"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"


def check_email() -> str:
    from app.email.factory import build_email_provider

    provider = build_email_provider(settings)
    return "OK" if provider is not None else "SKIP (не настроен, опционально)"


def check_tools() -> str:
    from app.tools.registry import default_registry

    return f"OK ({len(default_registry.all())} инструментов)"


def check_workers() -> str:
    try:
        from app.workers.job_worker import JobWorker  # noqa: F401
        from app.workers.reminder_worker import ReminderWorker  # noqa: F401

        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({exc})"


async def run() -> None:
    configure_logging(settings.log_level)
    print(f"Telegram: {await check_telegram()}")
    print(f"LLM ({settings.ai_provider}): {await check_llm()}")
    print(f"Database: {await check_database()}")
    print(f"Migrations: {await asyncio.to_thread(check_migrations)}")
    print(f"Playwright/Chromium: {await asyncio.to_thread(check_playwright_chromium)}")
    print(f"Avito session: {await check_avito()}")
    print(f"Email: {check_email()}")
    print(f"Tools: {check_tools()}")
    print(f"Workers: {check_workers()}")


if __name__ == "__main__":
    asyncio.run(run())
