from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.avito.pricing import compute_offer, draft_message, parse_price
from app.avito.scraper import extract_search_results, is_logged_in
from app.browser.session import browser_session
from app.config import Settings
from app.tools.avito_prepare_messages import AvitoPrepareMessagesTool
from app.tools.avito_read_listing import AvitoReadListingTool
from app.tools.avito_search import AvitoSearchTool
from app.tools.avito_send_messages import AvitoSendMessagesArgs, AvitoSendMessagesTool
from app.tools.base import ToolContext
from app.tools.permissions import PermissionLevel
from app.tools.registry import default_registry


# ---- pricing ----

def test_parse_price_strips_non_digits():
    assert parse_price("12 990 ₽") == 12990


def test_compute_offer_applies_discount():
    assert compute_offer(10000, 10) == 9000


def test_draft_message_without_discount():
    msg = draft_message("iPhone 17", "100000")
    assert "iPhone 17" in msg
    assert "%" not in msg


def test_draft_message_with_discount_includes_offer_price():
    msg = draft_message("iPhone 17", "100 000 ₽", discount_percent=10)
    assert "90000" in msg


# ---- scraper dedup ----

@pytest.mark.asyncio
async def test_extract_search_results_dedupes_and_limits():
    raw = [
        {"title": "A", "price": "1", "url": "https://avito.ru/1"},
        {"title": "A dup", "price": "1", "url": "https://avito.ru/1"},
        {"title": "B", "price": "2", "url": "https://avito.ru/2"},
        {"title": "C", "price": "3", "url": "https://avito.ru/3"},
    ]
    page = SimpleNamespace(eval_on_selector_all=AsyncMock(return_value=raw))

    results = await extract_search_results(page, limit=2)

    urls = [r["url"] for r in results]
    assert urls == ["https://avito.ru/1", "https://avito.ru/2"]  # без дублей, с лимитом


# ---- tool registration / schemas / permissions ----

def test_avito_tools_registered_with_expected_permissions():
    names = {"avito_search", "avito_read_listing", "avito_prepare_messages", "avito_send_messages"}
    assert names.issubset({t.name for t in default_registry.all()})

    assert default_registry.get("avito_search").permission == PermissionLevel.SAFE
    assert default_registry.get("avito_read_listing").permission == PermissionLevel.SAFE
    assert default_registry.get("avito_prepare_messages").permission == PermissionLevel.SAFE
    assert default_registry.get("avito_send_messages").permission == PermissionLevel.CONFIRM


def test_avito_search_schema_has_query_field():
    schema = AvitoSearchTool().input_schema()
    assert "query" in schema["properties"]


def test_avito_send_messages_rejects_more_than_ten():
    items = [{"url": f"https://avito.ru/{i}", "message": "hi"} for i in range(11)]
    with pytest.raises(ValidationError):
        AvitoSendMessagesArgs.model_validate({"messages": items})


def test_avito_send_messages_accepts_ten():
    items = [{"url": f"https://avito.ru/{i}", "message": "hi"} for i in range(10)]
    args = AvitoSendMessagesArgs.model_validate({"messages": items})
    assert len(args.messages) == 10


# ---- persistent browser config ----

def test_browser_session_uses_persistent_profile_settings():
    session = browser_session
    assert session._profile_dir.name == "browser-profile" or ".browser-profile" in str(session._profile_dir)
    assert hasattr(session, "get_page")
    assert hasattr(session, "close")


def test_settings_expose_browser_persistence_options():
    settings = Settings(browser_headless=False, browser_profile_dir="custom-profile")
    assert settings.browser_headless is False
    assert settings.browser_profile_dir == "custom-profile"


# ---- avito_prepare_messages / avito_read_listing / avito_search via tools ----

@pytest.mark.asyncio
async def test_prepare_messages_tool_builds_offer(db_session):
    ctx = ToolContext(user_id=1, session=db_session)
    result = await AvitoPrepareMessagesTool().run(
        ctx,
        listings=[{"title": "iPhone 17 Pro Max", "price": "150000", "url": "https://avito.ru/1"}],
        discount_percent=10,
    )
    assert "135000" in result
    assert "avito.ru/1" in result


@pytest.mark.asyncio
async def test_read_listing_stops_on_protection(db_session, monkeypatch):
    page = SimpleNamespace(
        goto=AsyncMock(),
        inner_text=AsyncMock(return_value="Пожалуйста, пройдите CAPTCHA"),
        url="https://avito.ru/1",
        is_closed=lambda: False,
    )
    monkeypatch.setattr(browser_session, "_page", page)
    ctx = ToolContext(user_id=1, session=db_session)

    result = await AvitoReadListingTool().run(ctx, url="https://avito.ru/1")

    assert "CAPTCHA" in result
    monkeypatch.setattr(browser_session, "_page", None)


@pytest.mark.asyncio
async def test_send_messages_stops_on_protection_and_skips_rest(db_session, monkeypatch):
    page = SimpleNamespace(
        goto=AsyncMock(),
        inner_text=AsyncMock(return_value="Подтвердите, что вы не робот"),
        url="https://avito.ru/1",
        is_closed=lambda: False,
    )
    monkeypatch.setattr(browser_session, "_page", page)
    ctx = ToolContext(user_id=1, session=db_session)

    result = await AvitoSendMessagesTool().run(
        ctx,
        messages=[
            {"url": "https://avito.ru/1", "message": "Здравствуйте"},
            {"url": "https://avito.ru/2", "message": "Здравствуйте"},
        ],
    )

    lines = result.splitlines()
    assert "skipped" in lines[0]
    assert "skipped" in lines[1]
    monkeypatch.setattr(browser_session, "_page", None)


# ---- avito_status (is_logged_in) ----

@pytest.mark.asyncio
async def test_is_logged_in_true_when_profile_accessible():
    page = SimpleNamespace(
        goto=AsyncMock(),
        inner_text=AsyncMock(return_value="Личные данные\nВыйти"),
        url="https://www.avito.ru/profile",
    )
    assert await is_logged_in(page) is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_redirected_to_login():
    page = SimpleNamespace(
        goto=AsyncMock(),
        inner_text=AsyncMock(return_value="Войти"),
        url="https://www.avito.ru/login",
    )
    assert await is_logged_in(page) is False


@pytest.mark.asyncio
async def test_is_logged_in_false_when_login_button_shown():
    page = SimpleNamespace(
        goto=AsyncMock(),
        inner_text=AsyncMock(return_value="Войти\nРегистрация"),
        url="https://www.avito.ru/profile",
    )
    assert await is_logged_in(page) is False
