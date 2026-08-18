from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError

from app.ai.coordinator import Coordinator
from app.ai.factory import build_provider
from app.browser.session import browser_session
from app.bot.handlers import build_router
from app.bot.middlewares import OwnerOnlyMiddleware
from app.config import settings
from app.db.bootstrap import ensure_postgres_ready
from app.logging_setup import configure_logging, get_logger
from app.stt.factory import build_stt_provider
from app.tools.registry import default_registry
from app.workers.job_worker import JobWorker
from app.workers.reminder_worker import ReminderWorker

logger = get_logger(__name__)

POLLING_RETRY_DELAY_SECONDS = 5


async def _ensure_database_ready() -> None:
    """Готовит PostgreSQL (запуск службы/создание БД при необходимости) и применяет
    alembic-миграции до head перед стартом — без ручных действий."""
    status = await ensure_postgres_ready(settings.database_url)
    if status != "OK":
        raise RuntimeError(status)

    from alembic import command
    from alembic.config import Config

    try:
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Миграции не применились: {type(exc).__name__}") from exc


async def _wait_for_telegram_ready(bot: Bot):
    """Таймаут/ошибка сети до api.telegram.org — сетевой blocker, а не баг: не падаем,
    а ждём и пробуем снова, пока сеть/VPN не восстановятся."""
    while True:
        try:
            me = await bot.get_me()
            await bot.delete_webhook(drop_pending_updates=False)
            return me
        except TelegramNetworkError:
            logger.warning("telegram_unreachable_network_blocker_retrying")
            await asyncio.sleep(POLLING_RETRY_DELAY_SECONDS)


async def _run_polling(bot: Bot, dp: Dispatcher) -> None:
    """dp.start_polling уже ретраит часть сетевых ошибок сам, но при 409 Conflict
    (второй запущенный экземпляр) или неожиданной ошибке выходит — не даём процессу
    падать совсем, логируем причину и пробуем снова."""
    while True:
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            return
        except TelegramConflictError:
            logger.error(
                "telegram_conflict_another_instance_running",
                hint="скорее всего запущен второй экземпляр бота с тем же токеном",
            )
            await asyncio.sleep(POLLING_RETRY_DELAY_SECONDS)
        except TelegramNetworkError:
            logger.warning("telegram_network_error_reconnecting")
            await asyncio.sleep(POLLING_RETRY_DELAY_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception("polling_failed_unexpectedly")
            await asyncio.sleep(POLLING_RETRY_DELAY_SECONDS)


async def main() -> None:
    configure_logging(settings.log_level)

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not settings.telegram_owner_id:
        raise RuntimeError("TELEGRAM_OWNER_ID не задан")

    await _ensure_database_ready()
    logger.info("database_ready")

    provider = build_provider(settings)
    stt_provider = build_stt_provider(settings)
    if stt_provider is None:
        logger.warning("stt_disabled")

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    coordinator = Coordinator(
        provider=provider,
        tool_registry=default_registry,
        history_window=settings.conversation_history_window,
        daily_token_limit=settings.daily_token_limit,
    )

    owner_only = OwnerOnlyMiddleware(settings.telegram_owner_id)
    dp.message.outer_middleware(owner_only)
    dp.callback_query.outer_middleware(owner_only)

    dp.include_router(build_router(coordinator, stt_provider))

    worker = ReminderWorker(bot, settings.telegram_owner_id, settings.reminder_poll_interval_seconds)
    worker_task = asyncio.create_task(worker.run())

    job_worker = JobWorker(
        bot, coordinator, settings.telegram_owner_id, settings.job_poll_interval_seconds, settings.job_max_runs
    )
    job_worker_task = asyncio.create_task(job_worker.run())

    me = await _wait_for_telegram_ready(bot)
    logger.info("bot_identity", username=me.username, bot_id=me.id)
    logger.info("webhook_deleted")

    logger.info("bot_starting")
    try:
        await _run_polling(bot, dp)
    finally:
        worker.stop()
        job_worker.stop()
        await worker_task
        await job_worker_task
        await browser_session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
