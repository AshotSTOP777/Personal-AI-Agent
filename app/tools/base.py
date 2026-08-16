from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.permissions import PermissionLevel


class ToolContext(BaseModel):
    """Контекст выполнения инструмента."""

    model_config = {"arbitrary_types_allowed": True}

    user_id: int
    session: AsyncSession


class Tool(ABC):
    """Базовый класс для всех инструментов агента."""

    name: str
    description: str
    args_schema: type[BaseModel]
    permission: PermissionLevel = PermissionLevel.SAFE

    def input_schema(self) -> dict[str, Any]:
        return self.args_schema.model_json_schema()

    def permission_for(self, tool_input: dict[str, Any]) -> PermissionLevel:
        """Позволяет инструменту переопределить permission в зависимости от аргументов
        (например, email_send на собственный адрес — SAFE, на любой другой — CONFIRM).
        По умолчанию возвращает статический self.permission."""
        return self.permission

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Выполняет инструмент и возвращает текстовый результат для модели."""
        raise NotImplementedError
