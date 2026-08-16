from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.ai.coordinator import Coordinator
from app.ai.factory import build_provider
from app.bot.handlers import build_router
from app.bot.middlewares import OwnerOnlyMiddleware
from app.config import settings
from app.logging_setup import configure_logging, get_logger
from app.tools.registry import default_registry
from app.workers.reminder_worker import ReminderWorker

logger = get_logger(__name__)


async def main() -> None:
    configure_logging(settings.log_level)

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not settings.telegram_owner_id:
        raise RuntimeError("TELEGRAM_OWNER_ID не задан")
    provider = build_provider(settings)

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

    dp.include_router(build_router(coordinator))

    worker = ReminderWorker(bot, settings.telegram_owner_id, settings.reminder_poll_interval_seconds)
    worker_task = asyncio.create_task(worker.run())

    logger.info("bot_starting")
    try:
        await dp.start_polling(bot)
    finally:
        worker.stop()
        await worker_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
