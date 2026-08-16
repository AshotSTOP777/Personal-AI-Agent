from __future__ import annotations

from pydantic import BaseModel, Field

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class BrowserSubmitArgs(BaseModel):
    selector: str | None = Field(
        default=None,
        description="CSS-селектор кнопки отправки формы. Если не указан — нажимается Enter.",
    )


class BrowserSubmitTool(Tool):
    name = "browser_submit"
    description = (
        "Отправляет форму на текущей странице (submit). Необратимое сетевое действие "
        "(регистрация, отправка данных) — требует подтверждения владельца."
    )
    args_schema = BrowserSubmitArgs
    permission = PermissionLevel.CONFIRM

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = BrowserSubmitArgs.model_validate(kwargs)
        try:
            return await browser_session.submit(args.selector)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось отправить форму: {exc}"
