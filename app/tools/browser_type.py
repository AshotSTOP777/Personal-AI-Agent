from __future__ import annotations

from pydantic import BaseModel, Field

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class BrowserTypeArgs(BaseModel):
    selector: str = Field(description="CSS-селектор поля ввода")
    text: str = Field(description="Текст, который нужно ввести в поле")


class BrowserTypeTool(Tool):
    name = "browser_type"
    description = "Вводит текст в поле формы на текущей странице браузера (не отправляет форму)."
    args_schema = BrowserTypeArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = BrowserTypeArgs.model_validate(kwargs)
        try:
            return await browser_session.type(args.selector, args.text)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось ввести текст в '{args.selector}': {exc}"
