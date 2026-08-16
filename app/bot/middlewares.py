from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.logging_setup import get_logger

logger = get_logger(__name__)


class OwnerOnlyMiddleware(BaseMiddleware):
    """Разрешает обработку событий только от владельца бота."""

    def __init__(self, owner_id: int) -> None:
        self._owner_id = owner_id
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")

        if user is not None and user.id != self._owner_id:
            logger.warning("unauthorized_access_attempt", user_id=user.id)
            if hasattr(event, "answer"):
                await event.answer("Этот бот приватный и не может выполнять твои поручения.")
            return None

        return await handler(event, data)
