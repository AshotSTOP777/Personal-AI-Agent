from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.config import settings
from app.services import reminder_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class CreateReminderArgs(BaseModel):
    text: str = Field(description="Текст напоминания")
    remind_at: dt.datetime = Field(
        description="Дата и время напоминания. Если без часового пояса — трактуется как часовой пояс владельца."
    )


class CreateReminderTool(Tool):
    name = "create_reminder"
    description = "Создаёт напоминание на конкретную дату и время (в часовом поясе владельца)."
    args_schema = CreateReminderArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = CreateReminderArgs.model_validate(kwargs)
        remind_at = args.remind_at
        if remind_at.tzinfo is None:
            try:
                local_tz = ZoneInfo(settings.user_timezone)
            except Exception:  # noqa: BLE001
                local_tz = dt.timezone.utc
            remind_at = remind_at.replace(tzinfo=local_tz)
        remind_at_utc = remind_at.astimezone(dt.timezone.utc)
        reminder = await reminder_service.create_reminder(ctx.session, ctx.user_id, args.text, remind_at_utc)

        try:
            display_tz = ZoneInfo(settings.user_timezone)
        except Exception:  # noqa: BLE001
            display_tz = dt.timezone.utc
        stored_utc = reminder.remind_at
        if stored_utc.tzinfo is None:  # sqlite не хранит tzinfo — считаем, что значение уже UTC
            stored_utc = stored_utc.replace(tzinfo=dt.timezone.utc)
        local_display = stored_utc.astimezone(display_tz)
        return f"Создал напоминание #{reminder.id} на {local_display.strftime('%Y-%m-%d %H:%M %Z')}: {reminder.text}"
