from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.services import reminder_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class CreateReminderArgs(BaseModel):
    text: str = Field(description="Текст напоминания")
    remind_at: dt.datetime = Field(description="Дата и время напоминания в формате ISO 8601 (с часовым поясом)")


class CreateReminderTool(Tool):
    name = "create_reminder"
    description = "Создаёт напоминание на конкретную дату и время."
    args_schema = CreateReminderArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = CreateReminderArgs.model_validate(kwargs)
        remind_at = args.remind_at
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=dt.timezone.utc)
        reminder = await reminder_service.create_reminder(ctx.session, ctx.user_id, args.text, remind_at)
        return f"Создал напоминание #{reminder.id} на {reminder.remind_at.isoformat()}: {reminder.text}"
