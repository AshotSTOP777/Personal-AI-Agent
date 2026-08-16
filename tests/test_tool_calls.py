from __future__ import annotations

from typing import Any

import pytest

from app.ai.base import AIProvider, AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import Coordinator
from app.services import conversation_service, task_service
from app.tools.registry import default_registry


class ScriptedProvider(AIProvider):
    """Фейковый провайдер, отдающий заранее заданную последовательность ответов."""

    def __init__(self, responses: list[AIResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def generate(self, system, messages, tools, max_tokens=1024) -> AIResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return self._responses.pop(0)


def _usage(input_tokens=10, output_tokens=5) -> TokenUsage:
    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)


@pytest.mark.asyncio
async def test_coordinator_executes_tool_and_returns_final_text(db_session):
    tool_call_response = AIResponse(
        text="",
        tool_calls=[ToolCall(id="call_1", name="create_task", input={"title": "Позвонить маме"})],
        raw_content=[{"type": "tool_use", "id": "call_1", "name": "create_task", "input": {"title": "Позвонить маме"}}],
        stop_reason="tool_use",
        usage=_usage(),
    )
    final_response = AIResponse(
        text="Создал задачу «Позвонить маме».",
        tool_calls=[],
        raw_content=[{"type": "text", "text": "Создал задачу «Позвонить маме»."}],
        stop_reason="end_turn",
        usage=_usage(),
    )
    provider = ScriptedProvider([tool_call_response, final_response])
    coordinator = Coordinator(
        provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000
    )

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Создай задачу позвонить маме")

    assert result.text == "Создал задачу «Позвонить маме»."
    assert result.pending_confirmation is None
    assert len(provider.calls) == 2

    tasks = await task_service.list_active_tasks(db_session, user_id=1)
    assert len(tasks) == 1
    assert tasks[0].title == "Позвонить маме"

    history = await conversation_service.get_recent_history(db_session, user_id=1, limit=10)
    roles = [m.role for m in history]
    assert roles == ["user", "assistant"]


@pytest.mark.asyncio
async def test_coordinator_respects_daily_token_limit(db_session):
    from app.services import usage_service

    await usage_service.log_usage(db_session, user_id=1, model="claude", input_tokens=100_000, output_tokens=100_000)

    provider = ScriptedProvider([])
    coordinator = Coordinator(
        provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=100_000
    )

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Привет")

    assert "лимит" in result.text.lower()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_coordinator_no_tool_calls_returns_text_directly(db_session):
    final_response = AIResponse(
        text="Привет! Чем могу помочь?",
        tool_calls=[],
        raw_content=[{"type": "text", "text": "Привет! Чем могу помочь?"}],
        stop_reason="end_turn",
        usage=_usage(),
    )
    provider = ScriptedProvider([final_response])
    coordinator = Coordinator(
        provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000
    )

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Привет")

    assert result.text == "Привет! Чем могу помочь?"
    assert len(provider.calls) == 1
