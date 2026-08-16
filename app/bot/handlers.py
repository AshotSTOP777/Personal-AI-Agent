from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.ai.coordinator import Coordinator
from app.bot.formatting import split_message
from app.db.session import session_scope
from app.logging_setup import get_logger
from app.services import memory_service, task_service

logger = get_logger(__name__)

router = Router(name="main")


def build_router(coordinator: Coordinator) -> Router:
    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Привет! Я твой личный AI-ассистент.\n"
            "Пиши поручения обычным текстом: найти информацию, поставить задачу, "
            "создать напоминание, запомнить факт.\n\n"
            "Команды: /help /tasks /memory /cancel"
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            "Примеры запросов:\n"
            "• Напомни завтра в 15:00 позвонить\n"
            "• Создай задачу на пятницу — подготовить отчёт\n"
            "• Запомни, что мой сервер находится на Hetzner\n"
            "• Какие у меня задачи?\n"
            "• Найди лучшие ноутбуки до 100000 рублей\n\n"
            "Команды: /tasks — активные задачи, /memory — последние факты в памяти, /cancel — отменить текущий запрос."
        )

    @router.message(Command("tasks"))
    async def cmd_tasks(message: Message) -> None:
        async with session_scope() as session:
            tasks = await task_service.list_active_tasks(session, message.from_user.id)
        if not tasks:
            await message.answer("Активных задач нет.")
            return
        lines = [f"#{t.id} {t.title}" + (f" (срок: {t.due_date})" if t.due_date else "") for t in tasks]
        await message.answer("\n".join(lines))

    @router.message(Command("memory"))
    async def cmd_memory(message: Message) -> None:
        async with session_scope() as session:
            memories = await memory_service.recall(session, message.from_user.id, query="", limit=10)
        if not memories:
            await message.answer("Память пока пуста.")
            return
        lines = [f"[{m.category}] {m.content}" for m in memories]
        await message.answer("\n".join(lines))

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message) -> None:
        await message.answer("Запросы обрабатываются по одному, отменять сейчас нечего.")

    @router.message()
    async def handle_text(message: Message) -> None:
        if not message.text:
            await message.answer("Я понимаю только текстовые сообщения.")
            return

        user_id = message.from_user.id
        await message.bot.send_chat_action(message.chat.id, "typing")

        try:
            async with session_scope() as session:
                result = await coordinator.handle_message(session, user_id, message.text)
        except Exception:  # noqa: BLE001
            logger.exception("handle_message_failed", user_id=user_id)
            await message.answer("Что-то пошло не так при обработке запроса. Попробуй ещё раз.")
            return

        for chunk in split_message(result.text or "Готово."):
            await message.answer(chunk)

    return router
