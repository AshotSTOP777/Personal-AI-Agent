from __future__ import annotations

import asyncio
import datetime as dt
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

_NO_UPDATE_MARKERS = ("ничего нового", "нет изменений", "пока нет", "изменений не найдено")
_FAILED_LOOP_MARKER = "не удалось завершить задачу"


def _is_no_update(text: str) -> bool:
    normalized = text.strip().lower()
    return any(normalized.startswith(marker) for marker in _NO_UPDATE_MARKERS)


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

    status = JobStatus.FAILED if result.text.lower().startswith(_FAILED_LOOP_MARKER) else JobStatus.DONE
    await job_service.update_job(
        session, job, status=status, context={"messages": [], "last_result": result.text},
        run_count=run_count, next_run_at=None,
    )
    return f"Задание #{job.id}: {result.text}"


class JobWorker:
    """Периодически продолжает долгоживущие задания (active/waiting) в PostgreSQL.

    Agent loop полностью переиспользуется через Coordinator.run_job_iteration — воркер
    только восстанавливает/сохраняет messages между запусками (Job.context) и решает,
    когда писать в Telegram: молчит, если результат не изменился ('Ничего нового.'),
    иначе сообщает и переводит job в done/failed. CONFIRM/CRITICAL действия ставят job
    на паузу (исключается из опроса, пока владелец не подтвердит) — защита от повторных
    одинаковых уведомлений и бесконечных циклов обеспечена самим статусом job и
    JOB_MAX_RUNS.
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

        messages_after = messages + [{"role": "assistant", "content": [{"type": "text", "text": result.text}]}]

        if _is_no_update(result.text):
            next_run_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=self._poll_interval)
            await job_service.update_job(
                session, job, status=JobStatus.WAITING,
                context={"messages": messages_after, "last_result": result.text},
                run_count=run_count, next_run_at=next_run_at,
            )
            return  # ничего нового — молчим, не спамим

        status = JobStatus.FAILED if result.text.lower().startswith(_FAILED_LOOP_MARKER) else JobStatus.DONE
        await job_service.update_job(
            session, job, status=status, context={"messages": messages_after, "last_result": result.text},
            run_count=run_count, next_run_at=None,
        )
        await self._notify(job, result.text)

    async def _notify(self, job: Job, text: str) -> None:
        clean = strip_markdown(text)
        for chunk in split_message(f"Задание #{job.id}: {clean}"):
            try:
                await self._bot.send_message(self._owner_id, chunk)
            except Exception:  # noqa: BLE001
                logger.exception("job_notify_failed", job_id=job.id)
                return
