from __future__ import annotations

import os
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.ai.coordinator import Coordinator
from app.bot.formatting import split_message
from app.config import settings
from app.db.session import session_scope
from app.logging_setup import get_logger
from app.services import memory_service, task_service
from app.stt.base import STTProvider

logger = get_logger(__name__)

router = Router(name="main")

_CONFIRMATION_WORDS = {"да", "подтверждаю", "confirm", "yes", "ок", "окей", "выполняй", "го", "y"}


def _is_confirmation(text: str) -> bool:
    return text.strip().strip(".!,").lower() in _CONFIRMATION_WORDS


async def handle_confirmation(message: Message, coordinator: Coordinator) -> None:
    """Выполняет ранее заблокированное на подтверждение действие напрямую — не отправляет
    слово подтверждения модели как новую задачу."""
    user_id = message.from_user.id
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        async with session_scope() as session:
            result = await coordinator.confirm_pending(session, user_id)
    except Exception:  # noqa: BLE001
        logger.exception("confirm_pending_failed", user_id=user_id)
        await message.answer("Что-то пошло не так при подтверждении действия. Попробуй ещё раз.")
        return

    for chunk in split_message(result.text or "Не удалось получить ответ."):
        await message.answer(chunk)


async def handle_text_message(message: Message, coordinator: Coordinator, user_text: str) -> None:
    """Отправляет текст в Coordinator и возвращает ответ. Используется как для обычных
    текстовых сообщений, так и для текста, распознанного из голосового сообщения —
    Coordinator обрабатывает его точно так же (память, инструменты, permissions)."""
    user_id = message.from_user.id
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        async with session_scope() as session:
            result = await coordinator.handle_message(session, user_id, user_text)
    except Exception:  # noqa: BLE001
        logger.exception("handle_message_failed", user_id=user_id)
        await message.answer("Что-то пошло не так при обработке запроса. Попробуй ещё раз.")
        return

    for chunk in split_message(result.text or "Не удалось получить ответ."):
        await message.answer(chunk)


async def _download_voice(message: Message, voice) -> bytes:
    """Скачивает голосовое/аудио сообщение во временный файл и сразу его удаляет."""
    tg_file = await message.bot.get_file(voice.file_id)
    fd, tmp_path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)
    try:
        await message.bot.download_file(tg_file.file_path, destination=tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def handle_voice_message(
    message: Message,
    coordinator: Coordinator,
    stt_provider: STTProvider | None,
    max_duration_seconds: int,
) -> None:
    voice = message.voice or message.audio
    if voice is None:
        return

    if voice.duration and voice.duration > max_duration_seconds:
        await message.answer(
            f"Голосовое сообщение длиннее {max_duration_seconds // 60} минут не поддерживается."
        )
        return

    if stt_provider is None:
        await message.answer("Распознавание голосовых сообщений не настроено. Напиши текстом.")
        return

    audio_bytes = await _download_voice(message, voice)

    try:
        text = await stt_provider.transcribe(audio_bytes, filename="voice.ogg")
    except Exception:  # noqa: BLE001
        logger.exception("stt_failed", user_id=message.from_user.id)
        await message.answer("Не удалось распознать голосовое сообщение. Попробуй ещё раз или напиши текстом.")
        return

    if not text.strip():
        await message.answer("Не удалось распознать текст в голосовом сообщении.")
        return

    await handle_text_message(message, coordinator, text)


def build_router(coordinator: Coordinator, stt_provider: STTProvider | None = None) -> Router:
    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Привет! Я твой личный AI-ассистент.\n"
            "Пиши поручения обычным текстом (или голосовым сообщением): найти информацию, "
            "поставить задачу, создать напоминание, запомнить факт.\n\n"
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
            "Можно писать текстом или голосовым сообщением (до "
            f"{settings.voice_max_duration_seconds // 60} минут).\n\n"
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
        had_pending = coordinator.has_pending(message.from_user.id)
        coordinator.clear_pending(message.from_user.id)
        if had_pending:
            await message.answer("Ожидающее подтверждения действие отменено.")
        else:
            await message.answer("Запросы обрабатываются по одному, отменять сейчас нечего.")

    @router.message(F.voice | F.audio)
    async def voice_handler(message: Message) -> None:
        await handle_voice_message(message, coordinator, stt_provider, settings.voice_max_duration_seconds)

    @router.message()
    async def text_handler(message: Message) -> None:
        if not message.text:
            await message.answer("Я понимаю текстовые и голосовые сообщения.")
            return

        user_id = message.from_user.id
        if coordinator.has_pending(user_id):
            if _is_confirmation(message.text):
                await handle_confirmation(message, coordinator)
                return
            coordinator.clear_pending(user_id)

        await handle_text_message(message, coordinator, message.text)

    return router
