from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.config import settings
from app.services import job_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class CreateJobArgs(BaseModel):
    goal: str = Field(description="Цель долгоживущего фонового задания")
    delay_seconds: int | None = Field(
        default=None, description="Через сколько секунд сделать первую проверку (по умолчанию — стандартный интервал)"
    )


class CreateJobTool(Tool):
    name = "create_job"
    description = (
        "Создаёт долгоживущее фоновое задание (например: 'проверяй раз в час', "
        "'жди ответ на письмо и продолжи', 'продолжи завтра'). Задание переживает "
        "перезапуск и продолжится автоматически, результат придёт в Telegram."
    )
    args_schema = CreateJobArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = CreateJobArgs.model_validate(kwargs)
        delay = args.delay_seconds if args.delay_seconds is not None else settings.job_poll_interval_seconds
        next_run_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(delay, 0))
        job = await job_service.create_job(ctx.session, ctx.user_id, args.goal, next_run_at=next_run_at)
        return f"Создал фоновое задание #{job.id}: {args.goal}"
