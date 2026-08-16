from __future__ import annotations

from pydantic import BaseModel, Field

from app.services import memory_service
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class RecallMemoryArgs(BaseModel):
    query: str = Field(description="Что нужно найти в памяти")
    limit: int = Field(default=5, ge=1, le=20, description="Максимум записей в ответе")


class RecallMemoryTool(Tool):
    name = "recall_memory"
    description = "Ищет релевантную информацию в долговременной памяти пользователя."
    args_schema = RecallMemoryArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = RecallMemoryArgs.model_validate(kwargs)
        memories = await memory_service.recall(ctx.session, ctx.user_id, args.query, args.limit)
        if not memories:
            return "В памяти ничего не найдено."
        lines = [f"[{m.category}] {m.content}" for m in memories]
        return "\n".join(lines)
