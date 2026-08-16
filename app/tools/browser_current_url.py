from __future__ import annotations

from pydantic import BaseModel

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class BrowserCurrentUrlArgs(BaseModel):
    pass


class BrowserCurrentUrlTool(Tool):
    name = "browser_current_url"
    description = "Возвращает URL текущей открытой в браузере страницы."
    args_schema = BrowserCurrentUrlArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        try:
            return await browser_session.current_url()
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось получить текущий URL: {exc}"
