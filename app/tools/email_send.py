from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from app.config import settings
from app.email.factory import build_email_provider
from app.logging_setup import get_logger
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

logger = get_logger(__name__)


class EmailSendArgs(BaseModel):
    to: str = Field(description="Email-адрес получателя")
    subject: str = Field(description="Тема письма")
    body: str = Field(description="Текст письма")


class EmailSendTool(Tool):
    name = "email_send"
    description = (
        "Отправляет email одному получателю через SMTP. Письмо на собственный адрес "
        "владельца (EMAIL_ADDRESS) отправляется сразу; на любой другой адрес — только "
        "после подтверждения владельца. Не используй для массовой рассылки."
    )
    args_schema = EmailSendArgs
    permission = PermissionLevel.CONFIRM

    def permission_for(self, tool_input: dict) -> PermissionLevel:
        to = str(tool_input.get("to", "")).strip().lower()
        own = settings.email_address.strip().lower()
        if own and to == own:
            return PermissionLevel.SAFE
        return PermissionLevel.CONFIRM

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = EmailSendArgs.model_validate(kwargs)
        provider = build_email_provider(settings)
        if provider is None:
            return "Email не настроен (EMAIL_ADDRESS/EMAIL_PASSWORD/SMTP_HOST/IMAP_HOST не заданы)."
        try:
            await asyncio.to_thread(provider.send, args.to, args.subject, args.body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("email_send_failed", error=str(exc))
            return f"Не удалось отправить письмо: {exc}"
        return f"Письмо отправлено на {args.to} (тема: «{args.subject}»)."
