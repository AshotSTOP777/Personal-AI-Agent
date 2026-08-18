from __future__ import annotations

from typing import Any

import pytest

from app.ai.base import AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import Coordinator, _infers_execute_intent
from app.tools.registry import default_registry


class ScriptedProvider:
    def __init__(self, responses: list[AIResponse]) -> None:
        self._responses = responses
        self.calls = 0

    async def generate(self, system, messages, tools, max_tokens=1024) -> AIResponse:
        self.calls += 1
        return self._responses.pop(0)


def _usage() -> TokenUsage:
    return TokenUsage(input_tokens=10, output_tokens=5)


def _tool_call_response(call_id: str, name: str, args: dict[str, Any]) -> AIResponse:
    return AIResponse(
        text="", tool_calls=[ToolCall(id=call_id, name=name, input=args)],
        raw_content=[{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        stop_reason="tool_use", usage=_usage(),
    )


def _final_response(text: str) -> AIResponse:
    return AIResponse(
        text=text, tool_calls=[], raw_content=[{"type": "text", "text": text}], stop_reason="end_turn", usage=_usage()
    )


def _make_coordinator(provider: ScriptedProvider) -> Coordinator:
    return Coordinator(provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Напиши продавцу и спроси цену", True),
        ("Отправь письмо поставщику", True),
        ("Свяжись с ними по почте", True),
        ("Зарегистрируй меня на сайте", True),
        ("Предложи продавцам скидку 10%", True),
        ("Подготовь черновик письма", False),
        ("Составь сообщение, но не отправляй", False),
        ("Покажи, что бы ты написал", False),
        ("Какая погода завтра?", False),
    ],
)
def test_infers_execute_intent(text, expected):
    assert _infers_execute_intent(text) is expected


@pytest.mark.asyncio
async def test_explicit_execute_intent_skips_confirmation(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "email_send", {"to": "supplier@example.com", "subject": "Цена", "body": "?"}),
            _final_response("Написал поставщику."),
        ]
    )
    coordinator = _make_coordinator(provider)

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Напиши поставщику и узнай цену")

    assert result.pending_confirmation is None
    assert len(sent) == 1  # выполнено сразу, без второго "да"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_prepare_intent_never_bypasses_confirmation(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    provider = ScriptedProvider(
        [_tool_call_response("call_1", "email_send", {"to": "supplier@example.com", "subject": "Цена", "body": "?"})]
    )
    coordinator = _make_coordinator(provider)

    # "составь ... и отправь" — PREPARE-глагол есть, поэтому даже при наличии "отправь"
    # автоматической отправки быть не должно.
    result = await coordinator.handle_message(
        db_session, user_id=1, user_text="Составь письмо поставщику и отправь"
    )

    assert result.pending_confirmation is not None
    assert len(sent) == 0


@pytest.mark.asyncio
async def test_execute_intent_bypasses_confirm_for_browser_submit(db_session, monkeypatch):
    from app.browser.session import browser_session

    class FakePage:
        def __init__(self) -> None:
            self.url = "https://example.com/signup"
            self.submitted = False

        def is_closed(self) -> bool:
            return False

        async def goto(self, url, timeout=None):
            self.url = url

        async def title(self):
            return "Sign up"

        async def fill(self, selector, text, timeout=None):
            pass

        async def click(self, selector, timeout=None):
            self.submitted = True

    fake_page = FakePage()
    monkeypatch.setattr(browser_session, "_page", fake_page)

    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "browser_submit", {"selector": "#submit"}),
            _final_response("Зарегистрировал."),
        ]
    )
    coordinator = _make_coordinator(provider)

    result = await coordinator.handle_message(
        db_session, user_id=1, user_text="Зарегистрируй меня на example.com/signup"
    )

    assert fake_page.submitted is True
    assert result.pending_confirmation is None

    monkeypatch.setattr(browser_session, "_page", None)


@pytest.mark.asyncio
async def test_critical_permission_never_bypassed_even_with_execute_intent(db_session, monkeypatch):
    from app.tools.base import Tool, ToolContext
    from app.tools.permissions import PermissionLevel

    class FakeCriticalArgs:
        pass

    class FakeCriticalTool(Tool):
        name = "fake_pay"
        description = "test-only critical tool"
        permission = PermissionLevel.CRITICAL

        class args_schema:
            @staticmethod
            def model_json_schema():
                return {}

        async def run(self, ctx: ToolContext, **kwargs) -> str:
            return "paid"

    default_registry.register(FakeCriticalTool())
    try:
        provider = ScriptedProvider([_tool_call_response("call_1", "fake_pay", {})])
        coordinator = _make_coordinator(provider)

        result = await coordinator.handle_message(db_session, user_id=1, user_text="Отправь оплату поставщику")

        assert result.pending_confirmation is not None
        assert result.pending_confirmation["tool_name"] == "fake_pay"
    finally:
        default_registry._tools.pop("fake_pay", None)
