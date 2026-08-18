from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.browser.session import browser_session
from app.tools.base import ToolContext
from app.tools.site_extract import SiteExtractTool
from app.tools.site_login_status import SiteLoginStatusTool


@pytest.mark.asyncio
async def test_site_extract_returns_json_list(db_session, monkeypatch):
    page = SimpleNamespace(
        eval_on_selector_all=AsyncMock(return_value=["Товар 1 — 100р", "Товар 2 — 200р"]),
        is_closed=lambda: False,
    )
    monkeypatch.setattr(browser_session, "_page", page)
    ctx = ToolContext(user_id=1, session=db_session)

    result = await SiteExtractTool().run(ctx, selector=".product")

    assert "Товар 1" in result
    monkeypatch.setattr(browser_session, "_page", None)


@pytest.mark.asyncio
async def test_site_login_status_detects_logged_in(db_session, monkeypatch):
    page = SimpleNamespace(inner_text=AsyncMock(return_value="Личный кабинет\nВыйти"), is_closed=lambda: False)
    monkeypatch.setattr(browser_session, "_page", page)
    ctx = ToolContext(user_id=1, session=db_session)

    result = await SiteLoginStatusTool().run(ctx)

    assert "Авториз" in result
    monkeypatch.setattr(browser_session, "_page", None)


@pytest.mark.asyncio
async def test_site_login_status_detects_logged_out(db_session, monkeypatch):
    page = SimpleNamespace(inner_text=AsyncMock(return_value="Войти\nРегистрация"), is_closed=lambda: False)
    monkeypatch.setattr(browser_session, "_page", page)
    ctx = ToolContext(user_id=1, session=db_session)

    result = await SiteLoginStatusTool().run(ctx)

    assert "Не авториз" in result
    monkeypatch.setattr(browser_session, "_page", None)
