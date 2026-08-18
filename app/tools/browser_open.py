from __future__ import annotations

from pydantic import BaseModel, Field

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel
from app.tools.url_safety import UnsafeUrlError, assert_url_allowed


class BrowserOpenArgs(BaseModel):
    url: str = Field(description="URL страницы, которую нужно открыть в браузере")


class BrowserOpenTool(Tool):
    name = "browser_open"
    description = (
        "Открывает страницу в реальном Chromium/Playwright с сохранённой пользовательской "
        "сессией. Предпочитай этот инструмент для Avito и других динамических сайтов, "
        "где нужны JavaScript, актуальные цены, авторизация, кнопки, формы или чаты."
    )
    args_schema = BrowserOpenArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = BrowserOpenArgs.model_validate(kwargs)
        try:
            assert_url_allowed(args.url)
        except UnsafeUrlError as exc:
            return f"Не удалось открыть страницу: {exc}"
        try:
            return await browser_session.open(args.url)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось открыть страницу: {exc}"
