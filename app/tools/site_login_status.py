from __future__ import annotations

from pydantic import BaseModel

from app.browser.session import browser_session, detect_protection
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

_LOGIN_MARKERS = ("войти", "log in", "sign in", "login")
_LOGGED_IN_MARKERS = ("выйти", "log out", "sign out", "logout", "личный кабинет", "profile", "мой профиль")


class SiteLoginStatusArgs(BaseModel):
    pass


class SiteLoginStatusTool(Tool):
    name = "site_login_status"
    description = (
        "Эвристически определяет, авторизован ли пользователь на текущей открытой странице "
        "(универсально для любого сайта, не только Avito)."
    )
    args_schema = SiteLoginStatusArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        try:
            page = await browser_session.get_page()
            text = (await page.inner_text("body")).lower()
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось проверить статус входа: {exc}"

        warning = detect_protection(text)
        if warning:
            return warning

        has_logout = any(marker in text for marker in _LOGGED_IN_MARKERS)
        has_login = any(marker in text for marker in _LOGIN_MARKERS)
        if has_logout and not has_login:
            return "Авторизован."
        if has_login:
            return "Не авторизован."
        return "Не удалось однозначно определить статус входа."
