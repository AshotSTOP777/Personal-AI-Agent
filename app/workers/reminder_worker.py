from __future__ import annotations

import asyncio

from aiogram import Bot

from app.db.session import session_scope
from app.logging_setup import get_logger
from app.services import reminder_service

logger = get_logger(__name__)


class ReminderWorker:
    """Периодически проверяет просроченные напоминания в БД и отправляет их владельцу.

    Напоминания хранятся в PostgreSQL, поэтому переживают перезапуск процесса —
    ничего не держим в памяти, кроме самого цикла опроса.
    """

    def __init__(self, bot: Bot, owner_id: int, poll_interval_seconds: int) -> None:
        self._bot = bot
        self._owner_id = owner_id
        self._poll_interval = poll_interval_seconds
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._check_due_reminders()
            except Exception:  # noqa: BLE001
                logger.exception("reminder_worker_iteration_failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()

    async def _check_due_reminders(self) -> None:
        async with session_scope() as session:
            due = await reminder_service.list_due_reminders(session)
            for reminder in due:
                try:
                    await self._bot.send_message(self._owner_id, f"⏰ Напоминание: {reminder.text}")
                except Exception:  # noqa: BLE001
                    logger.exception("reminder_send_failed", reminder_id=reminder.id)
                    continue
                await reminder_service.mark_sent(session, reminder.id)
