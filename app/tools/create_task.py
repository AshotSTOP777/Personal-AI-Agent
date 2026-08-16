from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.services import task_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class CreateTaskArgs(BaseModel):
    title: str = Field(description="Короткое название задачи")
    description: str | None = Field(default=None, description="Дополнительные детали задачи")
    due_date: dt.datetime | None = Field(default=None, description="Срок выполнения в формате ISO 8601, если есть")


class CreateTaskTool(Tool):
    name = "create_task"
    description = "Создаёт задачу/поручение для пользователя."
    args_schema = CreateTaskArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = CreateTaskArgs.model_validate(kwargs)
        task = await task_service.create_task(ctx.session, ctx.user_id, args.title, args.description, args.due_date)
        return f"Создал задачу #{task.id}: {task.title}"
