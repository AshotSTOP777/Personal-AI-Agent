from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from app.config import settings
from app.email.factory import build_email_provider
from app.logging_setup import get_logger
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

logger = get_logger(__name__)


class EmailSearchArgs(BaseModel):
    query: str = Field(description="Текст для поиска в теме или отправителе письма")
    limit: int = Field(default=5, ge=1, le=20, description="Максимум писем в ответе")


class EmailSearchTool(Tool):
    name = "email_search"
    description = "Ищет письма по теме или отправителю через IMAP."
    args_schema = EmailSearchArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = EmailSearchArgs.model_validate(kwargs)
        provider = build_email_provider(settings)
        if provider is None:
            return "Email не настроен (GMAIL_CLIENT_ID/GMAIL_REFRESH_TOKEN или EMAIL_ADDRESS/SMTP_HOST/IMAP_HOST не заданы)."
        try:
            messages = await asyncio.to_thread(provider.search, args.query, args.limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("email_search_failed", error=str(exc))
            return f"Не удалось выполнить поиск по почте: {exc}"

        if not messages:
            return "По запросу ничего не найдено."
        lines = [f"От: {m['from']} | {m['date']}\nТема: {m['subject']}\n{m['snippet']}" for m in messages]
        return "\n\n".join(lines)
