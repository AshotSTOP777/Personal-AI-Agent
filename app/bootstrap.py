from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.config import settings
from app.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)

ALEMBIC_INI_PATH = Path(__file__).resolve().parent.parent / "alembic.ini"


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
    from app.db.bootstrap import ensure_postgres_ready

    return await ensure_postgres_ready(settings.database_url)


async def check_migrations(db_status: str) -> str:
    if db_status != "OK":
        return "SKIP (база недоступна)"
    try:
        from alembic import command
        from alembic.config import Config

        await asyncio.to_thread(command.upgrade, Config(str(ALEMBIC_INI_PATH)), "head")
        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({type(exc).__name__})"


async def check_playwright_chromium() -> str:
    """Асинхронный Playwright API — используется тем же event loop, что и остальное
    приложение, без sync API в отдельном потоке (это и вызывало 'Event loop is closed'
    при выходе на Windows)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "FAIL (pip install playwright)"

    async def _launch_and_close() -> None:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()

    try:
        await _launch_and_close()
        return "OK"
    except Exception:  # noqa: BLE001
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium"
            )
            await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                return "FAIL (playwright install chromium завершился с ошибкой)"
            await _launch_and_close()
            return "OK (Chromium установлен автоматически)"
        except Exception as exc:  # noqa: BLE001
            return f"FAIL ({type(exc).__name__})"


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
    db_status = await check_database()
    print(f"Database: {db_status}")
    print(f"Migrations: {await check_migrations(db_status)}")
    print(f"Playwright/Chromium: {await check_playwright_chromium()}")
    print(f"Avito session: {await check_avito()}")
    print(f"Email: {check_email()}")
    print(f"Tools: {check_tools()}")
    print(f"Workers: {check_workers()}")

    from app.browser.session import browser_session

    await browser_session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
