from __future__ import annotations

from pydantic import BaseModel, Field

from app.services import memory_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class RememberArgs(BaseModel):
    content: str = Field(description="Факт или информация, которую нужно запомнить")
    category: str = Field(default="general", description="Категория факта, например: контакты, работа, здоровье")


class RememberTool(Tool):
    name = "remember"
    description = "Сохраняет важный факт в долговременную память пользователя."
    args_schema = RememberArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = RememberArgs.model_validate(kwargs)
        memory = await memory_service.remember(ctx.session, ctx.user_id, args.content, args.category)
        return f"Запомнил (id={memory.id}, категория={memory.category}): {memory.content}"
