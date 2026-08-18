from __future__ import annotations

from typing import Any

import pytest

from app.ai.base import AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import MAX_TOOL_ITERATIONS, Coordinator
from app.tools.registry import default_registry


class ScriptedProvider:
    def __init__(self, responses: list[AIResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def generate(self, system, messages, tools, max_tokens=1024) -> AIResponse:
        self.calls.append({"messages": messages, "tools": tools})
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


def _make_coordinator(provider: ScriptedProvider) -> Coordinator:
    return Coordinator(provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000)


@pytest.mark.asyncio
async def test_email_send_requires_confirmation_and_is_not_executed(db_session):
    provider = ScriptedProvider(
        [_tool_call_response("call_1", "email_send", {"to": "person@example.com", "subject": "Привет", "body": "Текст"})]
    )
    coordinator = _make_coordinator(provider)

    # Нейтральная формулировка без явного EXECUTE-намерения ("напиши"/"отправь" и т.п.) —
    # CONFIRM должен сработать. Явное намерение проверяется в test_intent_authorization.py.
    result = await coordinator.handle_message(db_session, user_id=1, user_text="Разберись с почтой для меня")

    assert result.pending_confirmation is not None
    assert result.pending_confirmation["tool_name"] == "email_send"
    assert len(provider.calls) == 1  # инструмент не выполнялся, второго вызова модели не было


@pytest.mark.asyncio
async def test_registration_flow_stops_before_submit(db_session, monkeypatch):
    """Coordinator должен открыть страницу, заполнить форму (SAFE), но остановиться и
    запросить подтверждение перед browser_submit, не отправляя форму."""
    from app.browser.session import browser_session

    class FakePage:
        def __init__(self) -> None:
            self.url = "https://example.com/signup"
            self.filled = False
            self.submitted = False

        def is_closed(self) -> bool:
            return False

        async def goto(self, url, timeout=None):
            self.url = url

        async def title(self):
            return "Sign up"

        async def fill(self, selector, text, timeout=None):
            self.filled = True

        async def click(self, selector, timeout=None):
            self.submitted = True

    fake_page = FakePage()
    monkeypatch.setattr(browser_session, "_page", fake_page)

    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "browser_open", {"url": "https://example.com/signup"}),
            _tool_call_response("call_2", "browser_type", {"selector": "#email", "text": "me@example.com"}),
            _tool_call_response("call_3", "browser_submit", {"selector": "#submit"}),
        ]
    )
    coordinator = _make_coordinator(provider)

    # Нейтральная формулировка (без явного "зарегистрируй") — CONFIRM должен сработать.
    result = await coordinator.handle_message(
        db_session, user_id=1, user_text="Разберись с сайтом example.com/signup"
    )

    assert fake_page.filled is True
    assert fake_page.submitted is False  # submit не выполнялся
    assert result.pending_confirmation is not None
    assert result.pending_confirmation["tool_name"] == "browser_submit"

    monkeypatch.setattr(browser_session, "_page", None)


@pytest.mark.asyncio
async def test_agent_loop_never_exceeds_max_tool_iterations(db_session):
    assert MAX_TOOL_ITERATIONS == 10

    responses = [_tool_call_response(f"call_{i}", "list_tasks", {}) for i in range(MAX_TOOL_ITERATIONS)]
    provider = ScriptedProvider(responses)
    coordinator = _make_coordinator(provider)

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Сделай много шагов подряд")

    assert len(provider.calls) == MAX_TOOL_ITERATIONS
    assert result.text  # не пустой ответ, а сообщение о превышении лимита шагов
    assert result.pending_confirmation is None


@pytest.mark.asyncio
async def test_final_answer_contains_real_tool_result_after_multi_step_run(db_session):
    """После выполнения нескольких безопасных шагов подряд финальный ответ должен
    содержать конкретный результат последнего инструмента, а не пустышку."""
    empty_final_response = AIResponse(
        text="", tool_calls=[], raw_content=[], stop_reason="end_turn", usage=_usage()
    )
    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "create_task", {"title": "Изучить сайт"}),
            _tool_call_response("call_2", "list_tasks", {}),
            empty_final_response,
        ]
    )
    coordinator = _make_coordinator(provider)

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Создай задачу и покажи список")

    assert "Изучить сайт" in result.text
    assert result.text not in ("Готово.", "")
