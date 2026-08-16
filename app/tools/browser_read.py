from __future__ import annotations

from pydantic import BaseModel

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class BrowserReadArgs(BaseModel):
    pass


class BrowserReadTool(Tool):
    name = "browser_read"
    description = (
        "Читает основной текст текущей открытой в браузере страницы. "
        "Предупреждает, если обнаружена CAPTCHA/2FA/антибот-защита."
    )
    args_schema = BrowserReadArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        try:
            return await browser_session.read()
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось прочитать страницу: {exc}"
