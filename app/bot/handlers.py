from __future__ import annotations

import os
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.ai.coordinator import Coordinator
from app.bot.formatting import split_message, strip_markdown
from app.browser.session import browser_session
from app.config import settings
from app.db.session import session_scope
from app.logging_setup import get_logger
from app.services import job_service, memory_service, task_service
from app.stt.base import STTProvider
from app.workers.job_worker import confirm_job

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

    for chunk in split_message(strip_markdown(result.text or "Не удалось получить ответ.")):
        await message.answer(chunk)


async def handle_job_confirmation(message: Message, coordinator: Coordinator, job_id: int) -> None:
    """Подтверждает действие, на котором стоит долгоживущее задание (job), и продолжает
    именно этот job — не отправляет слово подтверждения модели как новую задачу."""
    user_id = message.from_user.id
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        async with session_scope() as session:
            job = await job_service.get_job(session, job_id)
            if job is None:
                await message.answer("Задание не найдено.")
                return
            text = await confirm_job(session, coordinator, job)
    except Exception:  # noqa: BLE001
        logger.exception("confirm_job_failed", user_id=user_id, job_id=job_id)
        await message.answer("Что-то пошло не так при подтверждении задания. Попробуй ещё раз.")
        return

    for chunk in split_message(strip_markdown(text)):
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

    for chunk in split_message(strip_markdown(result.text or "Не удалось получить ответ.")):
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
            "Команды: /tasks — активные задачи, /memory — последние факты в памяти, "
            "/jobs — фоновые задания, /cancel_job <id> — остановить задание, "
            "/avito_login — открыть Avito в браузере для входа, /cancel — отменить текущий запрос."
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

    @router.message(Command("jobs"))
    async def cmd_jobs(message: Message) -> None:
        async with session_scope() as session:
            jobs = await job_service.list_active_jobs(session, message.from_user.id)
        if not jobs:
            await message.answer("Активных заданий нет.")
            return
        lines = [f"#{j.id} [{j.status.value}] {j.goal}" for j in jobs]
        await message.answer("\n".join(lines))

    @router.message(Command("cancel_job"))
    async def cmd_cancel_job(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer("Использование: /cancel_job <id>")
            return
        async with session_scope() as session:
            job = await job_service.cancel_job(session, message.from_user.id, int(arg))
        if job is None:
            await message.answer("Задание не найдено или уже завершено.")
            return
        await message.answer(f"Задание #{job.id} остановлено.")

    @router.message(Command("avito_login"))
    async def cmd_avito_login(message: Message) -> None:
        """Детерминированно открывает Avito в браузере — без LLM. При BROWSER_HEADLESS=false
        физически откроется окно Chromium для ручного входа (капча/смс/2FA — вручную)."""
        try:
            result = await browser_session.open("https://www.avito.ru")
        except Exception as exc:  # noqa: BLE001
            logger.exception("avito_login_failed")
            await message.answer(f"Не удалось открыть браузер: {exc}")
            return
        await message.answer(result)

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
        elif _is_confirmation(message.text):
            async with session_scope() as session:
                paused_job = await job_service.get_oldest_paused_job(session, user_id)
            if paused_job is not None:
                await handle_job_confirmation(message, coordinator, paused_job.id)
                return

        await handle_text_message(message, coordinator, message.text)

    return router
