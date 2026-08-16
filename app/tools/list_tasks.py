from __future__ import annotations

from pydantic import BaseModel

from app.services import task_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class ListTasksArgs(BaseModel):
    pass


class ListTasksTool(Tool):
    name = "list_tasks"
    description = "Возвращает список активных (незавершённых) задач пользователя."
    args_schema = ListTasksArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        tasks = await task_service.list_active_tasks(ctx.session, ctx.user_id)
        if not tasks:
            return "Активных задач нет."
        lines = [f"#{t.id} {t.title}" + (f" (срок: {t.due_date})" if t.due_date else "") for t in tasks]
        return "\n".join(lines)
