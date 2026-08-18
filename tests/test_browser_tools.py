from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.browser.session import browser_session
from app.tools.base import ToolContext
from app.tools.browser_click import BrowserClickTool
from app.tools.browser_current_url import BrowserCurrentUrlTool
from app.tools.browser_open import BrowserOpenTool
from app.tools.browser_read import BrowserReadTool
from app.tools.browser_type import BrowserTypeTool


@pytest.fixture(autouse=True)
def _fake_page():
    page = SimpleNamespace(
        url="https://example.com/signup",
        goto=AsyncMock(),
        title=AsyncMock(return_value="Sign up"),
        inner_text=AsyncMock(return_value="Заполните форму регистрации"),
        click=AsyncMock(),
        fill=AsyncMock(),
        is_closed=lambda: False,
    )
    browser_session._page = page
    yield page
    browser_session._page = None


@pytest.mark.asyncio
async def test_several_browser_tools_run_in_sequence_on_same_page(db_session, _fake_page):
    ctx = ToolContext(user_id=1, session=db_session)

    open_result = await BrowserOpenTool().run(ctx, url="https://example.com/signup")
    read_result = await BrowserReadTool().run(ctx)
    type_result = await BrowserTypeTool().run(ctx, selector="#email", text="me@example.com")
    click_result = await BrowserClickTool().run(ctx, selector="#next")
    url_result = await BrowserCurrentUrlTool().run(ctx)

    _fake_page.goto.assert_awaited_once_with("https://example.com/signup", timeout=browser_session._timeout_ms)
    _fake_page.fill.assert_awaited_once_with("#email", "me@example.com", timeout=browser_session._timeout_ms)
    _fake_page.click.assert_awaited_once_with("#next", timeout=browser_session._timeout_ms)

    assert "example.com/signup" in open_result
    assert "форму регистрации" in read_result
    assert "email" in type_result
    assert "next" in click_result
    assert url_result == "https://example.com/signup"


@pytest.mark.asyncio
async def test_browser_read_warns_on_captcha(db_session, _fake_page):
    _fake_page.inner_text = AsyncMock(return_value="Please complete the CAPTCHA to continue")
    ctx = ToolContext(user_id=1, session=db_session)

    result = await BrowserReadTool().run(ctx)

    assert "CAPTCHA" in result
    assert "владел" in result.lower()
