from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import ToolCall
from app.ai.coordinator import Coordinator, PendingAction
from app.bot.formatting import split_message, strip_markdown
from app.logging_setup import get_logger
from app.models.job import Job, JobStatus
from app.services import job_service

logger = get_logger(__name__)

_FAILED_LOOP_MARKER = "не удалось завершить задачу"
_OUTCOME_RE = re.compile(r"^\s*\[OUTCOME:(CONTINUE|WAIT|NEED_USER|DONE|FAILED)\]\s*", re.IGNORECASE)

# Backoff для WAIT/CONTINUE: не долбим LLM каждую минуту без необходимости, но и не
# позволяем "проверь через 3 дня" внезапно умереть — max каждые ~2 часа между прогонами.
_MIN_WAIT_BACKOFF_SECONDS = 60
_MAX_WAIT_BACKOFF_SECONDS = 2 * 60 * 60


def _parse_outcome(text: str) -> tuple[str, str]:
    """Возвращает (outcome, текст_без_тега). Если модель не поставила тег (старые job/
    сбой) — считаем WAIT, чтобы не завершать задачу молча по случайному совпадению строки."""
    match = _OUTCOME_RE.match(text)
    if not match:
        return "WAIT", text.strip()
    return match.group(1).upper(), _OUTCOME_RE.sub("", text, count=1).strip()


def _pending_to_context(pending: PendingAction) -> dict[str, Any]:
    return {
        "messages": pending.messages,
        "pending_tool": {
            "id": pending.tool_call.id,
            "name": pending.tool_call.name,
            "input": pending.tool_call.input,
        },
        "remaining_iterations": pending.remaining_iterations,
    }


def _pending_from_context(context: dict[str, Any]) -> PendingAction | None:
    data = context.get("pending_tool")
    if not data:
        return None
    return PendingAction(
        tool_call=ToolCall(id=data["id"], name=data["name"], input=data["input"]),
        messages=context.get("messages", []),
        remaining_iterations=context.get("remaining_iterations", 0),
    )


async def confirm_job(session: AsyncSession, coordinator: Coordinator, job: Job) -> str:
    """Выполняет заблокированный на паузе tool call job'а и продолжает его agent loop —
    ровно тот же принцип, что и Coordinator.confirm_pending для интерактивного чата."""
    pending = _pending_from_context(job.context)
    if pending is None:
        await job_service.update_job(session, job, status=JobStatus.FAILED)
        return f"Задание #{job.id}: не найдено состояние для подтверждения."

    result, new_pending = await coordinator.confirm_job_pending(session, job.user_id, pending)
    run_count = job.run_count + 1

    if new_pending is not None:
        await job_service.update_job(
            session, job, context=_pending_to_context(new_pending), run_count=run_count
        )
        return f"Задание #{job.id} снова ожидает подтверждения: {new_pending.tool_call.name}."

    return await _apply_outcome(session, job, result.text, run_count, base_messages=[])


async def resume_job_with_user_reply(
    session: AsyncSession, coordinator: Coordinator, job: Job, user_text: str
) -> str:
    """Продолжает job, которому для дальнейшей работы требовался ответ владельца
    (NEED_USER) — добавляет ответ как новый ход и продолжает тот же agent loop."""
    messages = job.context.get("messages") or [{"role": "user", "content": [{"type": "text", "text": job.goal}]}]
    messages = messages + [{"role": "user", "content": [{"type": "text", "text": user_text}]}]

    result, pending = await coordinator.run_job_iteration(session, job.user_id, messages, max_iterations=10, goal=job.goal)
    run_count = job.run_count + 1

    if pending is not None:
        await job_service.update_job(
            session, job, status=JobStatus.PAUSED, context=_pending_to_context(pending), run_count=run_count,
        )
        return f"Задание #{job.id}: {result.text}"

    return await _apply_outcome(session, job, result.text, run_count, base_messages=messages)


async def _apply_outcome(
    session: AsyncSession, job: Job, raw_text: str, run_count: int, *, base_messages: list[dict[str, Any]]
) -> str:
    outcome, text = _parse_outcome(raw_text)
    messages_after = base_messages + [{"role": "assistant", "content": [{"type": "text", "text": raw_text}]}]

    if raw_text.lower().startswith(_FAILED_LOOP_MARKER):
        outcome = "FAILED"

    if outcome == "NEED_USER":
        await job_service.update_job(
            session, job, status=JobStatus.PAUSED,
            context={"messages": messages_after, "needs_user": True, "last_result": text},
            run_count=run_count, next_run_at=None,
        )
        return text or f"Задание #{job.id}: нужен твой ответ."

    if outcome in ("DONE", "FAILED"):
        status = JobStatus.DONE if outcome == "DONE" else JobStatus.FAILED
        await job_service.update_job(
            session, job, status=status, context={"messages": messages_after, "last_result": text},
            run_count=run_count, next_run_at=None,
        )
        return text

    # CONTINUE/WAIT — не завершаем, планируем следующий прогон с backoff
    backoff = min(max(job.run_count * _MIN_WAIT_BACKOFF_SECONDS, _MIN_WAIT_BACKOFF_SECONDS), _MAX_WAIT_BACKOFF_SECONDS)
    next_run_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=backoff)
    await job_service.update_job(
        session, job, status=JobStatus.WAITING,
        context={"messages": messages_after, "last_result": text},
        run_count=run_count, next_run_at=next_run_at,
    )
    return text


class JobWorker:
    """Периодически продолжает долгоживущие задания (active/waiting) в PostgreSQL.

    Agent loop полностью переиспользуется через Coordinator.run_job_iteration — воркер
    только восстанавливает/сохраняет messages между запусками (Job.context) и решает,
    когда писать в Telegram, на основе структурированного [OUTCOME:...] тега, который
    обязана поставить модель (не хрупкое распознавание русской строки). CONFIRM/CRITICAL
    действия и NEED_USER ставят job на паузу — исключается из опроса, пока владелец не
    ответит; backoff и JOB_MAX_RUNS защищают от лишних прогонов и бесконечных циклов.
    """

    def __init__(
        self, bot: Bot, coordinator: Coordinator, owner_id: int, poll_interval_seconds: int, max_runs: int
    ) -> None:
        self._bot = bot
        self._coordinator = coordinator
        self._owner_id = owner_id
        self._poll_interval = poll_interval_seconds
        self._max_runs = max_runs
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._run_due_jobs()
            except Exception:  # noqa: BLE001
                logger.exception("job_worker_iteration_failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()

    async def _run_due_jobs(self) -> None:
        from app.db.session import session_scope

        async with session_scope() as session:
            due = await job_service.list_due_jobs(session, max_runs=self._max_runs)
            for job in due:
                await self.run_job(session, job)

    async def run_job(self, session: AsyncSession, job: Job) -> None:
        if job.run_count >= self._max_runs:
            await job_service.update_job(session, job, status=JobStatus.FAILED, next_run_at=None)
            await self._notify(job, f"остановлено: превышен лимит прогонов ({self._max_runs}).")
            return

        messages = job.context.get("messages") or [
            {"role": "user", "content": [{"type": "text", "text": job.goal}]}
        ]

        result, pending = await self._coordinator.run_job_iteration(
            session, job.user_id, messages, max_iterations=10, goal=job.goal
        )
        run_count = job.run_count + 1

        if pending is not None:
            await job_service.update_job(
                session, job, status=JobStatus.PAUSED, context=_pending_to_context(pending),
                run_count=run_count, next_run_at=None,
            )
            await self._notify(job, result.text)
            return

        text = await _apply_outcome(session, job, result.text, run_count, base_messages=messages)

        # Пишем в Telegram только когда задание реально требует внимания владельца
        # (завершилось, упало или ждёт ответа) — WAIT/CONTINUE всегда молчат, чтобы не спамить.
        refreshed = await job_service.get_job(session, job.id)
        if refreshed is not None and refreshed.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.PAUSED):
            await self._notify(job, text)

    async def _notify(self, job: Job, text: str) -> None:
        clean = strip_markdown(text)
        for chunk in split_message(f"Задание #{job.id}: {clean}"):
            try:
                await self._bot.send_message(self._owner_id, chunk)
            except Exception:  # noqa: BLE001
                logger.exception("job_notify_failed", job_id=job.id)
                return
