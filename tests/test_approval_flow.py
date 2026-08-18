from __future__ import annotations

from typing import Any

import pytest

from app.ai.base import AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import Coordinator
from app.tools.email_send import EmailSendTool
from app.tools.permissions import PermissionLevel
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
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, input=args)],
        raw_content=[{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        stop_reason="tool_use",
        usage=_usage(),
    )


def _final_response(text: str) -> AIResponse:
    return AIResponse(
        text=text, tool_calls=[], raw_content=[{"type": "text", "text": text}], stop_reason="end_turn", usage=_usage()
    )


def _make_coordinator(provider: ScriptedProvider) -> Coordinator:
    return Coordinator(provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000)


def test_email_to_own_address_is_safe(monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    tool = EmailSendTool()
    assert tool.permission_for({"to": " Owner@Example.com "}) == PermissionLevel.SAFE


def test_email_to_other_address_requires_confirm(monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    tool = EmailSendTool()
    assert tool.permission_for({"to": "friend@example.com"}) == PermissionLevel.CONFIRM


@pytest.mark.asyncio
async def test_email_to_own_address_executes_immediately(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "email_send", {"to": "owner@example.com", "subject": "Заметка", "body": "Текст"}),
            _final_response("Письмо себе отправлено."),
        ]
    )
    coordinator = _make_coordinator(provider)

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Напиши мне заметку на почту")

    assert result.pending_confirmation is None
    assert len(sent) == 1
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_email_to_other_address_asks_for_confirmation(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    provider = ScriptedProvider(
        [_tool_call_response("call_1", "email_send", {"to": "friend@example.com", "subject": "Hi", "body": "Text"})]
    )
    coordinator = _make_coordinator(provider)

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Разберись с другом по почте")

    assert result.pending_confirmation == {
        "tool_name": "email_send",
        "input": {"to": "friend@example.com", "subject": "Hi", "body": "Text"},
    }
    assert len(sent) == 0
    assert provider.calls == 1
    assert coordinator.has_pending(1) is True


@pytest.mark.asyncio
async def test_confirm_pending_executes_once_and_continues_loop(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "email_send", {"to": "friend@example.com", "subject": "Hi", "body": "Text"}),
            _final_response("Письмо отправлено другу."),
        ]
    )
    coordinator = _make_coordinator(provider)

    first = await coordinator.handle_message(db_session, user_id=1, user_text="Разберись с другом по почте")
    assert first.pending_confirmation is not None
    assert provider.calls == 1

    second = await coordinator.confirm_pending(db_session, user_id=1)

    assert len(sent) == 1
    assert sent[0][0] == "friend@example.com"
    assert second.text == "Письмо отправлено другу."
    assert second.pending_confirmation is None
    assert provider.calls == 2  # loop продолжился новым вызовом модели с tool_result
    assert coordinator.has_pending(1) is False


@pytest.mark.asyncio
async def test_repeated_confirm_does_not_resend(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "email_send", {"to": "friend@example.com", "subject": "Hi", "body": "Text"}),
            _final_response("Письмо отправлено другу."),
        ]
    )
    coordinator = _make_coordinator(provider)

    await coordinator.handle_message(db_session, user_id=1, user_text="Разберись с другом по почте")
    await coordinator.confirm_pending(db_session, user_id=1)
    again = await coordinator.confirm_pending(db_session, user_id=1)

    assert len(sent) == 1  # письмо отправлено ровно один раз
    assert again.text == "Нет действия, ожидающего подтверждения."


def test_clear_pending_removes_state(db_session):
    coordinator = _make_coordinator(ScriptedProvider([]))
    from app.ai.coordinator import PendingAction

    coordinator._pending[1] = PendingAction(
        tool_call=ToolCall(id="x", name="email_send", input={}), messages=[], remaining_iterations=1
    )
    assert coordinator.has_pending(1) is True

    coordinator.clear_pending(1)

    assert coordinator.has_pending(1) is False
