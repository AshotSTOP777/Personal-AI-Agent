from __future__ import annotations

from pydantic import BaseModel, Field

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class BrowserClickArgs(BaseModel):
    selector: str = Field(description="CSS-селектор элемента, по которому нужно кликнуть")


class BrowserClickTool(Tool):
    name = "browser_click"
    description = "Кликает по элементу на текущей странице браузера (например, ссылка или кнопка)."
    args_schema = BrowserClickArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = BrowserClickArgs.model_validate(kwargs)
        try:
            return await browser_session.click(args.selector)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось кликнуть по '{args.selector}': {exc}"
