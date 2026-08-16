from __future__ import annotations

from pydantic import BaseModel, Field

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class BrowserOpenArgs(BaseModel):
    url: str = Field(description="URL страницы, которую нужно открыть в браузере")


class BrowserOpenTool(Tool):
    name = "browser_open"
    description = "Открывает страницу по URL в headless-браузере."
    args_schema = BrowserOpenArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = BrowserOpenArgs.model_validate(kwargs)
        try:
            return await browser_session.open(args.url)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось открыть страницу: {exc}"
