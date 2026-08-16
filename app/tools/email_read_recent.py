from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from app.config import settings
from app.email.factory import build_email_provider
from app.logging_setup import get_logger
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

logger = get_logger(__name__)


class EmailReadRecentArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=20, description="Сколько последних писем прочитать")


class EmailReadRecentTool(Tool):
    name = "email_read_recent"
    description = "Читает последние письма из входящих через IMAP."
    args_schema = EmailReadRecentArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = EmailReadRecentArgs.model_validate(kwargs)
        provider = build_email_provider(settings)
        if provider is None:
            return "Email не настроен (EMAIL_ADDRESS/EMAIL_PASSWORD/SMTP_HOST/IMAP_HOST не заданы)."
        try:
            messages = await asyncio.to_thread(provider.read_recent, args.limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("email_read_failed", error=str(exc))
            return f"Не удалось прочитать почту: {exc}"

        if not messages:
            return "Входящие пусты."
        lines = [f"От: {m['from']} | {m['date']}\nТема: {m['subject']}\n{m['snippet']}" for m in messages]
        return "\n\n".join(lines)
