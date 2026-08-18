from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.base import AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import Coordinator
from app.browser.session import browser_session
from app.tools.base import ToolContext
from app.tools.browser_open import BrowserOpenTool
from app.tools.registry import default_registry


def _usage() -> TokenUsage:
    return TokenUsage(input_tokens=10, output_tokens=5)


class ScriptedProvider:
    def __init__(self, responses):
        self._responses = responses

    async def generate(self, system, messages, tools, max_tokens=1024):
        return self._responses.pop(0)


def _make_coordinator(provider) -> Coordinator:
    return Coordinator(provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000)


# ---- single-instance lock ----

def test_single_instance_lock_prevents_second_launch():
    from app import main as app_main

    app_main._acquire_single_instance_lock()
    try:
        with pytest.raises(RuntimeError, match="Уже запущен"):
            app_main._acquire_single_instance_lock()
    finally:
        app_main._release_single_instance_lock()


# ---- browser_open SSRF guard ----

@pytest.mark.asyncio
async def test_browser_open_blocks_private_ip(db_session):
    ctx = ToolContext(user_id=1, session=db_session)
    result = await BrowserOpenTool().run(ctx, url="http://192.168.1.1/admin")
    assert "запрещ" in result.lower()


@pytest.mark.asyncio
async def test_browser_open_blocks_non_http_scheme(db_session):
    ctx = ToolContext(user_id=1, session=db_session)
    result = await BrowserOpenTool().run(ctx, url="file:///etc/passwd")
    assert "http/https" in result.lower()


# ---- safe finalizer: no raw JSON dumped to the user ----

@pytest.mark.asyncio
async def test_coordinator_never_dumps_raw_json_as_final_answer(db_session):
    tool_call = AIResponse(
        text="",
        tool_calls=[ToolCall(id="c1", name="avito_search", input={"query": "телефон"})],
        raw_content=[{"type": "tool_use", "id": "c1", "name": "avito_search", "input": {"query": "телефон"}}],
        stop_reason="tool_use",
        usage=_usage(),
    )
    empty_final = AIResponse(text="", tool_calls=[], raw_content=[], stop_reason="end_turn", usage=_usage())

    async def fake_avito_run(self, ctx, **kwargs):
        return '[{"title": "iPhone", "price": "10000", "url": "https://avito.ru/1"}]'

    from app.tools.avito_search import AvitoSearchTool

    original_run = AvitoSearchTool.run
    AvitoSearchTool.run = fake_avito_run
    try:
        provider = ScriptedProvider([tool_call, empty_final])
        coordinator = _make_coordinator(provider)

        result = await coordinator.handle_message(db_session, user_id=1, user_text="Найди телефон")

        assert not result.text.strip().startswith("[")
        assert not result.text.strip().startswith("{")
    finally:
        AvitoSearchTool.run = original_run


# ---- browser lock serializes concurrent access ----

@pytest.mark.asyncio
async def test_run_exclusive_serializes_concurrent_calls(monkeypatch):
    page = SimpleNamespace(is_closed=lambda: False)
    monkeypatch.setattr(browser_session, "_page", page)

    order: list[str] = []

    async def slow_action(p):
        order.append("start-A")
        await asyncio.sleep(0.05)
        order.append("end-A")

    async def fast_action(p):
        order.append("start-B")
        order.append("end-B")

    await asyncio.gather(
        browser_session.run_exclusive(slow_action),
        browser_session.run_exclusive(fast_action),
    )

    # Без сериализации fast_action успел бы вклиниться между start-A и end-A.
    assert order == ["start-A", "end-A", "start-B", "end-B"]
    monkeypatch.setattr(browser_session, "_page", None)
