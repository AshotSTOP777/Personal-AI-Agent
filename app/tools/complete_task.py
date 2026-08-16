from __future__ import annotations

from pydantic import BaseModel, Field

from app.services import task_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class CompleteTaskArgs(BaseModel):
    task_id: int = Field(description="ID задачи, которую нужно отметить выполненной")


class CompleteTaskTool(Tool):
    name = "complete_task"
    description = "Отмечает задачу выполненной по её ID."
    args_schema = CompleteTaskArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = CompleteTaskArgs.model_validate(kwargs)
        task = await task_service.complete_task(ctx.session, ctx.user_id, args.task_id)
        if task is None:
            return f"Задача #{args.task_id} не найдена."
        return f"Задача #{task.id} отмечена выполненной."
